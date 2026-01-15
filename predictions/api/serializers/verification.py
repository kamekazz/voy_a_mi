"""
Serializers for phone verification during registration and login.
"""
import re
from rest_framework import serializers
from predictions.models import User
from predictions.services import normalize_phone_number


class StartRegistrationSerializer(serializers.Serializer):
    """Serializer for starting phone registration."""
    username = serializers.CharField(min_length=3, max_length=30)
    phone_number = serializers.CharField(max_length=20)

    def validate_username(self, value):
        """Validate username format and uniqueness."""
        if not re.match(r'^[a-zA-Z0-9_]+$', value):
            raise serializers.ValidationError(
                "Username can only contain letters, numbers, and underscores.",
                code='invalid_username'
            )

        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError(
                "This username is already taken.",
                code='username_taken'
            )

        return value.lower()

    def validate_phone_number(self, value):
        """Validate and normalize phone number."""
        try:
            normalized = normalize_phone_number(value)
        except ValueError as e:
            raise serializers.ValidationError(
                str(e),
                code='invalid_phone'
            )

        if User.objects.filter(phone_number=normalized).exists():
            raise serializers.ValidationError(
                "This phone number is already registered.",
                code='phone_registered'
            )

        return normalized


class ConfirmRegistrationSerializer(serializers.Serializer):
    """Serializer for confirming phone registration."""
    phone_number = serializers.CharField(max_length=20)
    code = serializers.CharField(min_length=6, max_length=6)

    def validate_phone_number(self, value):
        """Normalize phone number."""
        try:
            return normalize_phone_number(value)
        except ValueError as e:
            raise serializers.ValidationError(
                str(e),
                code='invalid_phone'
            )

    def validate_code(self, value):
        """Validate code format."""
        if not value.isdigit():
            raise serializers.ValidationError(
                "Verification code must be 6 digits.",
                code='invalid_code_format'
            )
        return value


class StartLoginSerializer(serializers.Serializer):
    """Serializer for starting phone login."""
    phone_number = serializers.CharField(max_length=20)

    def validate_phone_number(self, value):
        """Validate and normalize phone number, ensure user exists."""
        try:
            normalized = normalize_phone_number(value)
        except ValueError as e:
            raise serializers.ValidationError(
                str(e),
                code='invalid_phone'
            )

        if not User.objects.filter(phone_number=normalized).exists():
            raise serializers.ValidationError(
                "No account found with this phone number.",
                code='user_not_found'
            )

        return normalized


class ConfirmLoginSerializer(serializers.Serializer):
    """Serializer for confirming phone login."""
    phone_number = serializers.CharField(max_length=20)
    code = serializers.CharField(min_length=6, max_length=6)

    def validate_phone_number(self, value):
        """Normalize phone number."""
        try:
            return normalize_phone_number(value)
        except ValueError as e:
            raise serializers.ValidationError(
                str(e),
                code='invalid_phone'
            )

    def validate_code(self, value):
        """Validate code format."""
        if not value.isdigit():
            raise serializers.ValidationError(
                "Verification code must be 6 digits.",
                code='invalid_code_format'
            )
        return value


class VerificationResponseSerializer(serializers.Serializer):
    """Response serializer for verification start endpoints."""
    message = serializers.CharField()
    phone_number = serializers.CharField()
    expires_in = serializers.IntegerField()


class AuthResponseSerializer(serializers.Serializer):
    """Response serializer for successful authentication."""
    user = serializers.DictField()
    tokens = serializers.DictField()
