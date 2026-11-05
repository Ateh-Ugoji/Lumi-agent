"""``/api/v1/auth/*``. See docs/CONTRATOS.md section 3.1."""

from __future__ import annotations

from django.contrib.auth.hashers import check_password, make_password
from django.db import IntegrityError, transaction
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import AuthToken, User
from apps.accounts.serializers import (
    AuthResponseSerializer,
    LoginSerializer,
    RegisterSerializer,
    UserSerializer,
)
from apps.accounts.throttles import AuthEmailThrottle, AuthIpThrottle
from apps.core.errors import ApiError

# Checked when the email is unknown so both failures cost the same time.
_DUMMY_HASH = make_password("not-a-real-password")
BAD_CREDENTIALS = "Email o contraseña incorrectos."


def _issued(user: User, name: str) -> dict:
    _, key = AuthToken.issue(user, name=name)
    return {"token": key, "user": UserSerializer(user).data}


class _PublicAuthView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [AuthIpThrottle, AuthEmailThrottle]


class RegisterView(_PublicAuthView):
    @extend_schema(request=RegisterSerializer, responses={201: AuthResponseSerializer})
    def post(self, request):
        data = RegisterSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        email = data.validated_data["email"]
        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    email,
                    data.validated_data["password"],
                    display_name=data.validated_data.get("display_name", ""),
                )
        except IntegrityError:
            raise ApiError(
                "conflict",
                "Ya existe una cuenta con ese email.",
                status_code=status.HTTP_409_CONFLICT,
            ) from None
        return Response(_issued(user, "register"), status=status.HTTP_201_CREATED)


class LoginView(_PublicAuthView):
    @extend_schema(request=LoginSerializer, responses={200: AuthResponseSerializer})
    def post(self, request):
        data = LoginSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = User.objects.filter(email=data.validated_data["email"]).first()
        password = data.validated_data["password"]
        if user is None:
            check_password(password, _DUMMY_HASH)
        if user is None or not user.check_password(password) or not user.is_active:
            raise ApiError(
                "unauthenticated",
                BAD_CREDENTIALS,
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        return Response(_issued(user, data.validated_data.get("device_name", "")))


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={204: None})
    def post(self, request):
        AuthToken.objects.filter(pk=request.auth.pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: UserSerializer})
    def get(self, request):
        return Response(UserSerializer(request.user).data)
