"""HTTP layer for ``/api/v1/connections``. See docs/CONTRATOS.md section 4."""

from __future__ import annotations

from django.http import HttpResponseRedirect
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import accounts
from .serializers import (
    ConnectRequestSerializer,
    ConnectResponseSerializer,
    DisconnectSerializer,
    StatusSerializer,
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
    """Public: the provider's browser redirect carries no Token header.

    The user is identified by the ``oauth_states`` row. The answer is always a 302 to the
    frontend, never JSON, and never echoes the provider's code or error text.
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]

    @extend_schema(
        responses={302: None},
        parameters=[
            OpenApiParameter("code", str),
            OpenApiParameter("state", str),
            OpenApiParameter("error", str),
        ],
        summary="OAuth redirect target. Answers 302 to the frontend",
    )
    def get(self, request, provider: str):
        target = accounts.finish_callback(provider, request.query_params.dict())
        response = HttpResponseRedirect(target)
        response["Cache-Control"] = "no-store"
        response["Referrer-Policy"] = "no-referrer"
        return response


class ProviderView(APIView):
    @extend_schema(responses=StatusSerializer, summary="Connection status")
    def get(self, request, provider: str):
        status = accounts.provider_status(request.user, provider)
        return Response(
            StatusSerializer(
                {
                    "provider": status.provider,
                    "configured": status.configured,
                    "connected": status.connected,
                    "stale": status.stale,
                    "accounts": status.accounts,
                }
            ).data
        )

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
