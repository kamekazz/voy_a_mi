from rest_framework import serializers
from predictions.models import User, UserPreferences


class UserSerializer(serializers.ModelSerializer):
    """Public user info (minimal)."""

    class Meta:
        model = User
        fields = ['id', 'username']
        read_only_fields = ['id', 'username']


class UserProfileSerializer(serializers.ModelSerializer):
    """Full user profile with token information."""
    available_tokens = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True
    )

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'phone_number',
            'email',
            'first_name',
            'last_name',
            'tokens',
            'reserved_tokens',
            'available_tokens',
            'date_joined',
        ]
        read_only_fields = [
            'id',
            'username',
            'phone_number',
            'tokens',
            'reserved_tokens',
            'available_tokens',
            'date_joined',
        ]


class UserPreferencesSerializer(serializers.ModelSerializer):
    """User preferences serializer."""

    class Meta:
        model = UserPreferences
        fields = ['ui_mode']
