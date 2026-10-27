"""``/api/v1/chat/*``. See docs/CONTRATOS.md sections 3.3 and 3.4."""

from __future__ import annotations

from asgiref.sync import async_to_sync
from django.http import StreamingHttpResponse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.chat import services, sse
from apps.chat.serializers import (
    ChatRequestSerializer,
    HistoryQuerySerializer,
    TitleRequestSerializer,
)
from apps.core import agent_runtime as runtime
from apps.core.errors import ApiError
from apps.core.permissions import IsProfileOwner
from apps.core.throttles import ChatUserThrottle


def _require_profile_id(request) -> int:
    """``IsProfileOwner`` lets a request with no ``profile_id`` through; chat needs one."""
    profile = getattr(request, "profile", None)
    if profile is None:
        raise ApiError(
            "validation_error",
            "profile_id es obligatorio.",
            details={"profile_id": ["Este campo es obligatorio."]},
        )
    return profile.pk


class _ChatView(APIView):
    permission_classes = [IsProfileOwner]
    throttle_classes = [ChatUserThrottle]


class ChatView(_ChatView):
    def post(self, request):
        data = ChatRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        profile_id = _require_profile_id(request)
        result = async_to_sync(runtime.get_runtime().run_turn)(
            profile_id, data.validated_data["message"]
        )
        return Response(
            {
                "role": "assistant",
                "content": result.content,
                "tool_calls_made": list(result.tool_calls_made),
                "tool_executions": [e.as_dict() for e in result.tool_executions],
            }
        )


class ChatStreamView(_ChatView):
    def post(self, request):
        data = ChatRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        profile_id = _require_profile_id(request)
        events = runtime.get_runtime().stream_turn(
            profile_id, data.validated_data["message"]
        )
        response = StreamingHttpResponse(
            sse.stream(events), content_type="text/event-stream"
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response


class ChatHistoryView(_ChatView):
    def get(self, request):
        query = HistoryQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        profile_id = _require_profile_id(request)
        messages = services.history_page(
            profile_id,
            limit=query.validated_data["limit"],
            before=query.validated_data.get("before"),
        )
        return Response(
            {
                "messages": [
                    {
                        "id": m.id,
                        "role": m.role,
                        "content": m.content,
                        "created_at": m.created_at,
                    }
                    for m in messages
                ]
            }
        )

    def delete(self, request):
        services.clear_history(_require_profile_id(request))
        return Response(status=status.HTTP_204_NO_CONTENT)


class ChatTitleView(_ChatView):
    def post(self, request):
        data = TitleRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        title = async_to_sync(runtime.make_title)(data.validated_data["message"])
        return Response({"title": title})
