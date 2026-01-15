"""
Phone verification views for registration and login.
Uses Twilio Verify API for carrier-compliant SMS verification.
"""
from datetime import timedelta
from django.utils import timezone
from django.db import transaction
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from drf_spectacular.utils import extend_schema, OpenApiResponse

from predictions.models import User, PendingVerification
from predictions.api.serializers import (
    StartRegistrationSerializer,
    ConfirmRegistrationSerializer,
    StartLoginSerializer,
    ConfirmLoginSerializer,
    VerificationResponseSerializer,
    AuthResponseSerializer,
)
from predictions.services import (
    send_verification_code,
    check_verification_code,
)


VERIFICATION_EXPIRY_MINUTES = 10
MAX_REQUESTS_PER_HOUR = 5
RESEND_COOLDOWN_SECONDS = 30


class StartRegistrationView(APIView):
    """Start phone registration by sending verification code."""
    permission_classes = [AllowAny]

    @extend_schema(
        request=StartRegistrationSerializer,
        responses={
            201: VerificationResponseSerializer,
            400: OpenApiResponse(description='Validation error'),
            429: OpenApiResponse(description='Rate limit exceeded'),
        },
        tags=['auth'],
        summary='Start registration',
        description='Send verification code to phone number for new user registration.'
    )
    def post(self, request):
        serializer = StartRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        username = serializer.validated_data['username']
        phone_number = serializer.validated_data['phone_number']

        # Check rate limit
        one_hour_ago = timezone.now() - timedelta(hours=1)
        recent_requests = PendingVerification.objects.filter(
            phone_number=phone_number,
            created_at__gte=one_hour_ago
        ).count()

        if recent_requests >= MAX_REQUESTS_PER_HOUR:
            return Response(
                {'error': 'Too many verification requests. Try again later.', 'code': 'rate_limit_exceeded'},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

        # Check resend cooldown
        recent_pending = PendingVerification.objects.filter(
            phone_number=phone_number,
            type=PendingVerification.Type.REGISTRATION,
            status=PendingVerification.Status.PENDING
        ).order_by('-created_at').first()

        if recent_pending:
            cooldown_expires = recent_pending.last_request_at + timedelta(seconds=RESEND_COOLDOWN_SECONDS)
            if timezone.now() < cooldown_expires:
                wait_seconds = int((cooldown_expires - timezone.now()).total_seconds())
                return Response(
                    {'error': f'Please wait {wait_seconds} seconds before requesting another code.', 'code': 'cooldown_active'},
                    status=status.HTTP_429_TOO_MANY_REQUESTS
                )

        # Invalidate any existing pending verifications for this phone
        PendingVerification.objects.filter(
            phone_number=phone_number,
            type=PendingVerification.Type.REGISTRATION,
            status=PendingVerification.Status.PENDING
        ).update(status=PendingVerification.Status.EXPIRED)

        expires_at = timezone.now() + timedelta(minutes=VERIFICATION_EXPIRY_MINUTES)

        # Create new verification record (Twilio handles the code)
        PendingVerification.objects.create(
            type=PendingVerification.Type.REGISTRATION,
            username=username,
            phone_number=phone_number,
            code_hash='twilio_verify',  # Twilio manages the code
            expires_at=expires_at,
        )

        # Send verification via Twilio Verify
        try:
            send_verification_code(phone_number)
        except Exception as e:
            return Response(
                {'error': 'Failed to send verification code. Please try again.', 'code': 'sms_failed', 'detail': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response({
            'message': 'Verification code sent',
            'phone_number': phone_number,
            'expires_in': VERIFICATION_EXPIRY_MINUTES * 60
        }, status=status.HTTP_201_CREATED)


class ConfirmRegistrationView(APIView):
    """Confirm registration with verification code and create user."""
    permission_classes = [AllowAny]

    @extend_schema(
        request=ConfirmRegistrationSerializer,
        responses={
            201: AuthResponseSerializer,
            400: OpenApiResponse(description='Validation error or invalid code'),
            404: OpenApiResponse(description='Verification not found'),
        },
        tags=['auth'],
        summary='Confirm registration',
        description='Verify code and create new user account.'
    )
    def post(self, request):
        serializer = ConfirmRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone_number = serializer.validated_data['phone_number']
        code = serializer.validated_data['code']

        # Find pending verification
        verification = PendingVerification.objects.filter(
            phone_number=phone_number,
            type=PendingVerification.Type.REGISTRATION,
            status=PendingVerification.Status.PENDING
        ).order_by('-created_at').first()

        if not verification:
            return Response(
                {'error': 'No pending verification found. Please start registration again.', 'code': 'verification_not_found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Check if expired
        if verification.is_expired:
            verification.status = PendingVerification.Status.EXPIRED
            verification.save()
            return Response(
                {'error': 'Verification code has expired. Please request a new one.', 'code': 'code_expired'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Verify code with Twilio Verify API
        if not check_verification_code(phone_number, code):
            verification.failed_attempts += 1
            verification.save()
            return Response(
                {'error': 'Invalid verification code.', 'code': 'invalid_code'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Re-check username availability (race condition protection)
        if User.objects.filter(username__iexact=verification.username).exists():
            return Response(
                {'error': 'Username was taken while verifying. Please start registration again.', 'code': 'username_taken'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Re-check phone availability
        if User.objects.filter(phone_number=phone_number).exists():
            return Response(
                {'error': 'Phone number was registered while verifying. Please try logging in.', 'code': 'phone_registered'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Create user
        with transaction.atomic():
            user = User.objects.create(
                username=verification.username,
                phone_number=phone_number,
            )
            user.set_unusable_password()
            user.save()

            # Mark verification as complete
            verification.status = PendingVerification.Status.VERIFIED
            verification.save()

        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)

        return Response({
            'user': {
                'id': user.id,
                'username': user.username,
                'phone_number': user.phone_number,
                'tokens': str(user.tokens),
                'available_tokens': str(user.available_tokens),
            },
            'tokens': {
                'access': str(refresh.access_token),
                'refresh': str(refresh),
            }
        }, status=status.HTTP_201_CREATED)


class StartLoginView(APIView):
    """Start phone login by sending verification code."""
    permission_classes = [AllowAny]

    @extend_schema(
        request=StartLoginSerializer,
        responses={
            200: VerificationResponseSerializer,
            400: OpenApiResponse(description='Validation error'),
            404: OpenApiResponse(description='User not found'),
            429: OpenApiResponse(description='Rate limit exceeded'),
        },
        tags=['auth'],
        summary='Start login',
        description='Send verification code to phone number for existing user login.'
    )
    def post(self, request):
        serializer = StartLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone_number = serializer.validated_data['phone_number']

        # Check rate limit
        one_hour_ago = timezone.now() - timedelta(hours=1)
        recent_requests = PendingVerification.objects.filter(
            phone_number=phone_number,
            created_at__gte=one_hour_ago
        ).count()

        if recent_requests >= MAX_REQUESTS_PER_HOUR:
            return Response(
                {'error': 'Too many verification requests. Try again later.', 'code': 'rate_limit_exceeded'},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

        # Check resend cooldown
        recent_pending = PendingVerification.objects.filter(
            phone_number=phone_number,
            type=PendingVerification.Type.LOGIN,
            status=PendingVerification.Status.PENDING
        ).order_by('-created_at').first()

        if recent_pending:
            cooldown_expires = recent_pending.last_request_at + timedelta(seconds=RESEND_COOLDOWN_SECONDS)
            if timezone.now() < cooldown_expires:
                wait_seconds = int((cooldown_expires - timezone.now()).total_seconds())
                return Response(
                    {'error': f'Please wait {wait_seconds} seconds before requesting another code.', 'code': 'cooldown_active'},
                    status=status.HTTP_429_TOO_MANY_REQUESTS
                )

        # Invalidate any existing pending verifications for this phone
        PendingVerification.objects.filter(
            phone_number=phone_number,
            type=PendingVerification.Type.LOGIN,
            status=PendingVerification.Status.PENDING
        ).update(status=PendingVerification.Status.EXPIRED)

        expires_at = timezone.now() + timedelta(minutes=VERIFICATION_EXPIRY_MINUTES)

        # Create new verification record
        PendingVerification.objects.create(
            type=PendingVerification.Type.LOGIN,
            phone_number=phone_number,
            code_hash='twilio_verify',  # Twilio manages the code
            expires_at=expires_at,
        )

        # Send verification via Twilio Verify
        try:
            send_verification_code(phone_number)
        except Exception as e:
            return Response(
                {'error': 'Failed to send verification code. Please try again.', 'code': 'sms_failed', 'detail': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response({
            'message': 'Verification code sent',
            'phone_number': phone_number,
            'expires_in': VERIFICATION_EXPIRY_MINUTES * 60
        }, status=status.HTTP_200_OK)


class ConfirmLoginView(APIView):
    """Confirm login with verification code and return JWT tokens."""
    permission_classes = [AllowAny]

    @extend_schema(
        request=ConfirmLoginSerializer,
        responses={
            200: AuthResponseSerializer,
            400: OpenApiResponse(description='Validation error or invalid code'),
            404: OpenApiResponse(description='Verification not found'),
        },
        tags=['auth'],
        summary='Confirm login',
        description='Verify code and return JWT tokens for existing user.'
    )
    def post(self, request):
        serializer = ConfirmLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone_number = serializer.validated_data['phone_number']
        code = serializer.validated_data['code']

        # Find pending verification
        verification = PendingVerification.objects.filter(
            phone_number=phone_number,
            type=PendingVerification.Type.LOGIN,
            status=PendingVerification.Status.PENDING
        ).order_by('-created_at').first()

        if not verification:
            return Response(
                {'error': 'No pending verification found. Please start login again.', 'code': 'verification_not_found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Check if expired
        if verification.is_expired:
            verification.status = PendingVerification.Status.EXPIRED
            verification.save()
            return Response(
                {'error': 'Verification code has expired. Please request a new one.', 'code': 'code_expired'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Verify code with Twilio Verify API
        if not check_verification_code(phone_number, code):
            verification.failed_attempts += 1
            verification.save()
            return Response(
                {'error': 'Invalid verification code.', 'code': 'invalid_code'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get user
        try:
            user = User.objects.get(phone_number=phone_number)
        except User.DoesNotExist:
            return Response(
                {'error': 'User account not found.', 'code': 'user_not_found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Mark verification as complete
        verification.status = PendingVerification.Status.VERIFIED
        verification.save()

        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)

        return Response({
            'user': {
                'id': user.id,
                'username': user.username,
                'phone_number': user.phone_number,
                'tokens': str(user.tokens),
                'available_tokens': str(user.available_tokens),
            },
            'tokens': {
                'access': str(refresh.access_token),
                'refresh': str(refresh),
            }
        }, status=status.HTTP_200_OK)
