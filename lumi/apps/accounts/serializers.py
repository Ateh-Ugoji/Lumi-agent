from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.accounts.models import User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "display_name"]
        read_only_fields = fields


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(
        write_only=True, trim_whitespace=False, max_length=128
    )
    display_name = serializers.CharField(
        max_length=120, required=False, allow_blank=True
    )

    def validate_email(self, value: str) -> str:
        return value.strip().lower()

    def validate(self, attrs):
        probe = User(email=attrs["email"], display_name=attrs.get("display_name", ""))
        try:
            validate_password(attrs["password"], user=probe)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                {"password": list(exc.messages)}
            ) from None
        return attrs


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(
        write_only=True, trim_whitespace=False, max_length=128
    )
    device_name = serializers.CharField(max_length=80, required=False, allow_blank=True)

    def validate_email(self, value: str) -> str:
        return value.strip().lower()


class AuthResponseSerializer(serializers.Serializer):
    token = serializers.CharField()
    user = UserSerializer()
