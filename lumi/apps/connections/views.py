"""HTTP layer for ``/api/v1/connections``. See docs/CONTRATOS.md section 4."""

from __future__ import annotations

from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status as http_status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.errors import ApiError
from apps.core.permissions import IsStaff, get_owned_profile

from . import (
    account_links,
    accounts,
    handles_api,
    publish_api,
    service_credentials,
)
from .serializers import (
    CallbackRequestSerializer,
    CallbackResponseSerializer,
    ConnectRequestSerializer,
    ConnectResponseSerializer,
    DisconnectSerializer,
    HandleSavedQuerySerializer,
    HandleSavedResponseSerializer,
    HandleSearchQuerySerializer,
    HandleSearchResponseSerializer,
    HandleSelectResponseSerializer,
    HandleSelectSerializer,
    HandleStatsSerializer,
    LinkRequestSerializer,
    LinkResponseSerializer,
    PublishRequestSerializer,
    PublishResponseSerializer,
    ServiceCredentialQuerySerializer,
    ServiceCredentialSerializer,
    ServiceSerializer,
    StatusSerializer,
)
from .throttles import (
    HandleSearchThrottle,
    PfmSyncThrottle,
    PublishThrottle,
    ServiceCredentialThrottle,
)


class ConnectView(APIView):
    @extend_schema(
        request=ConnectRequestSerializer,
        responses=ConnectResponseSerializer,
        summary="Start the connect flow and return the provider URL",
    )
    def post(self, request, provider: str):
        body = ConnectRequestSerializer(data=request.data or {})
        body.is_valid(raise_exception=True)
        data = body.validated_data
        url = accounts.start_connect(
            request.user,
            provider,
            redirect_after=data.get("redirect_after"),
            profile_id=data.get("profile_id"),
            platform=data.get("platform"),
        )
        return Response({"authorize_url": url})


class CallbackView(APIView):
    """Authenticated: the frontend page the provider redirects to posts ``code`` and ``state``.

    The provider's ``redirect_uri`` is a frontend page, never this API, because only the
    frontend holds the user's Token. The state must belong to the caller: a state started by
    someone else answers 409 and stays unused. Post for Me has no state and no code here.
    """

    @extend_schema(
        request=CallbackRequestSerializer,
        responses=CallbackResponseSerializer,
        summary="Finish an OAuth grant with the code the provider returned",
    )
    def post(self, request, provider: str):
        accounts.ensure_callback_provider(provider)  # before the body is validated
        body = CallbackRequestSerializer(data=request.data or {})
        body.is_valid(raise_exception=True)
        data = body.validated_data
        result = accounts.complete_connect(
            request.user,
            provider,
            state=data["state"],
            code=data.get("code", ""),
            error=data.get("error", ""),
        )
        response = Response(CallbackResponseSerializer(result).data)
        response["Cache-Control"] = "no-store"
        return response


def _status_body(status) -> dict:
    return StatusSerializer(
        {
            "provider": status.provider,
            "configured": status.configured,
            "connected": status.connected,
            "stale": status.stale,
            "accounts": status.accounts,
            "details": status.details,
        }
    ).data


class PfmSyncView(APIView):
    """Post for Me gives Lumi no ``state``: the user comes back to a page and this call reads
    their accounts. It is a POST because it calls PFM and writes ``connected_accounts``."""

    throttle_classes = [PfmSyncThrottle]

    def check_throttles(self, request):
        """DRF throttles before it looks for the method, so a GET would answer 429 (and spend
        the budget) instead of 405. Only a method this view handles counts against the limit."""
        if hasattr(self, request.method.lower()):
            super().check_throttles(request)

    @extend_schema(
        request=None,
        responses=StatusSerializer,
        summary="Read the user's Post for Me accounts and store them",
    )
    def post(self, request):
        return Response(_status_body(accounts.sync_pfm(request.user)))


class LinkView(APIView):
    """Choose which connected account publishes for a profile. See CONTRATOS 4.1."""

    @extend_schema(
        request=LinkRequestSerializer,
        responses=LinkResponseSerializer,
        summary="Link a connected account (a Meta Page, say) to one of the user's profiles",
    )
    def post(self, request, provider: str):
        account_links.ensure_linkable(provider)  # before the body, like the callback
        body = LinkRequestSerializer(data=request.data or {})
        body.is_valid(raise_exception=True)
        data = body.validated_data
        # Ownership is checked here, after the type check, so a malformed id is a 400.
        profile = get_owned_profile(request.user, data["profile_id"])
        result = account_links.link_account(
            request.user, provider, account_id=data["account_id"], profile=profile
        )
        return Response(LinkResponseSerializer(result).data)


class ProviderView(APIView):
    @extend_schema(
        responses=StatusSerializer, summary="Connection status (read only, no writes)"
    )
    def get(self, request, provider: str):
        return Response(_status_body(accounts.provider_status(request.user, provider)))

    @extend_schema(
        responses=DisconnectSerializer,
        parameters=[OpenApiParameter("account_id", str)],
        summary="Disconnect and delete the stored tokens",
    )
    def delete(self, request, provider: str):
        result = accounts.disconnect(
            request.user, provider, account_id=request.query_params.get("account_id")
        )
        return Response(DisconnectSerializer(result).data)


class HandleSearchView(APIView):
    throttle_classes = [HandleSearchThrottle]

    @extend_schema(
        parameters=[HandleSearchQuerySerializer],
        responses=HandleSearchResponseSerializer,
        summary="Search @-handles. Live lookups cost Xpoz credits and are off by default",
    )
    def get(self, request):
        query = HandleSearchQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        d = query.validated_data
        return Response(
            handles_api.search(request.user, d["q"], d["context"], d["platforms"])
        )


class HandleSavedView(APIView):
    @extend_schema(
        parameters=[HandleSavedQuerySerializer],
        responses=HandleSavedResponseSerializer,
        summary="Handles Lumi already knows, for instant suggestions. Costs nothing",
    )
    def get(self, request):
        query = HandleSavedQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return Response(
            handles_api.saved(request.user, query.validated_data["platforms"])
        )


class HandleSelectView(APIView):
    @extend_schema(
        request=HandleSelectSerializer,
        responses=HandleSelectResponseSerializer,
        summary="Remember a picked handle",
    )
    def post(self, request):
        body = HandleSelectSerializer(data=request.data or {})
        body.is_valid(raise_exception=True)
        result = handles_api.select(request.user, body.validated_data)
        if result is None:
            raise ApiError(
                "validation_error",
                "El handle no es válido.",
                details={"handle": ["Usa letras, números, punto, guion o guion bajo."]},
            )
        return Response(result)


class HandleStatsView(APIView):
    @extend_schema(responses=HandleStatsSerializer, summary="Credit meter and counts")
    def get(self, request):
        return Response(handles_api.stats(request.user))


class PublishView(APIView):
    throttle_classes = [PublishThrottle]

    @extend_schema(
        request=PublishRequestSerializer,
        parameters=[OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER)],
        responses={200: PublishResponseSerializer, 201: PublishResponseSerializer},
        summary="Publish a draft. Needs confirm=true and an Idempotency-Key unless dry_run",
    )
    def post(self, request):
        body = PublishRequestSerializer(data=request.data or {})
        body.is_valid(raise_exception=True)
        data = body.validated_data
        result = publish_api.publish_post(
            request.user,
            profile_id=data["profile_id"],
            platform=data["platform"],
            text=data.get("text"),
            attempt_id=data.get("attempt_id"),
            link=data.get("link"),
            confirm=data["confirm"],
            dry_run=data["dry_run"],
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        created = result["status"] == "done" and not result["replayed"]
        return Response(
            PublishResponseSerializer(result).data,
            status=http_status.HTTP_201_CREATED if created else http_status.HTTP_200_OK,
        )


@method_decorator(sensitive_post_parameters("app_secret"), name="dispatch")
class _StaffOnlyView(APIView):
    """Base of the credential routes: active staff only, rate limited, never cached."""

    permission_classes = [IsStaff]
    throttle_classes = [ServiceCredentialThrottle]

    def check_throttles(self, request):
        """Only a method this view handles counts against the limit (a GET on a POST-only route
        answers 405, not 429)."""
        if hasattr(self, request.method.lower()):
            super().check_throttles(request)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response


class ServiceListView(_StaffOnlyView):
    @extend_schema(
        responses=ServiceSerializer(many=True), summary="Catalog of services (staff only)"
    )
    def get(self, request):
        rows = service_credentials.list_services()
        return Response({"services": ServiceSerializer(rows, many=True).data})


class ServiceCredentialListView(_StaffOnlyView):
    @extend_schema(
        parameters=[ServiceCredentialQuerySerializer],
        responses=ServiceCredentialSerializer(many=True),
        summary="List app credentials, never with the secret (staff only)",
    )
    def get(self, request):
        query = ServiceCredentialQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        rows = service_credentials.list_credentials(
            service=query.validated_data.get("service"),
            environment=query.validated_data.get("environment"),
            active=query.validated_data.get("active"),
        )
        return Response(
            {"credentials": ServiceCredentialSerializer(rows, many=True).data}
        )

    @extend_schema(
        request=ServiceCredentialSerializer,
        responses={201: ServiceCredentialSerializer},
        summary="Store an app credential. The secret is encrypted and never returned",
    )
    def post(self, request):
        body = ServiceCredentialSerializer(data=request.data or {})
        body.is_valid(raise_exception=True)
        row = service_credentials.create_credential(request.user, body.validated_data)
        return Response(
            ServiceCredentialSerializer(row).data, status=http_status.HTTP_201_CREATED
        )


class ServiceCredentialDetailView(_StaffOnlyView):
    @extend_schema(
        responses=ServiceCredentialSerializer, summary="One app credential, no secret"
    )
    def get(self, request, pk: int):
        row = service_credentials.get_credential(pk)
        return Response(ServiceCredentialSerializer(row).data)

    @extend_schema(
        request=ServiceCredentialSerializer,
        responses=ServiceCredentialSerializer,
        summary="Change an app credential. Omit app_secret to keep the stored one",
    )
    def patch(self, request, pk: int):
        row = service_credentials.get_credential(pk)
        body = ServiceCredentialSerializer(row, data=request.data or {}, partial=True)
        body.is_valid(raise_exception=True)
        row = service_credentials.update_credential(
            request.user, row, body.validated_data
        )
        return Response(ServiceCredentialSerializer(row).data)

    @extend_schema(responses={204: None}, summary="Delete an app credential")
    def delete(self, request, pk: int):
        service_credentials.delete_credential(
            request.user, service_credentials.get_credential(pk)
        )
        return Response(status=http_status.HTTP_204_NO_CONTENT)
