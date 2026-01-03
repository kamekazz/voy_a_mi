from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from predictions.models import User, UserPreferences


class UserSerializer(serializers.ModelSerializer):
    """Public user info (minimal)."""

    class Meta:
        model = User
        fields = ['id', 'username']
        read_only_fields = ['id', 'username']


class UserProfileSerializer(serializers.ModelSerializer):
    """Full user profile with balance information."""
    available_balance = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True
    )

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'email',
            'first_name',
            'last_name',
            'balance',
            'reserved_balance',
            'available_balance',
            'date_joined',
        ]
        read_only_fields = [
            'id',
            'username',
            'balance',
            'reserved_balance',
            'available_balance',
            'date_joined',
        ]


class UserRegistrationSerializer(serializers.ModelSerializer):
    """Serializer for user registration."""
    password = serializers.CharField(
        write_only=True,
        required=True,
        validators=[validate_password],
        style={'input_type': 'password'}
    )
    password_confirm = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'}
    )
    email = serializers.EmailField(required=True)

    class Meta:
        model = User
        fields = [
            'username',
            'email',
            'password',
            'password_confirm',
            'first_name',
            'last_name',
        ]

    def validate_email(self, value):
        """Check that email is unique."""
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate_username(self, value):
        """Check that username is unique."""
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("A user with this username already exists.")
        return value

    def validate(self, attrs):
        """Validate that passwords match."""
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({
                "password_confirm": "Passwords do not match."
            })
        return attrs

    def create(self, validated_data):
        """Create user with hashed password."""
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')

        user = User.objects.create(**validated_data)
        user.set_password(password)
        user.save()

        # UserPreferences is auto-created by signal in predictions/signals.py

        return user


class UserPreferencesSerializer(serializers.ModelSerializer):
    """User preferences serializer."""

    class Meta:
        model = UserPreferences
        fields = ['ui_mode']
