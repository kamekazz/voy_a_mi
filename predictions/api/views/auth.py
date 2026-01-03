from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from drf_spectacular.utils import extend_schema

from predictions.api.serializers import UserRegistrationSerializer, UserProfileSerializer


class RegisterView(APIView):
    """
    User registration endpoint.

    POST /api/auth/register/
    Create a new user account and return user data with tokens.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        request=UserRegistrationSerializer,
        responses={
            201: {
                'type': 'object',
                'properties': {
                    'user': {'type': 'object'},
                    'tokens': {
                        'type': 'object',
                        'properties': {
                            'access': {'type': 'string'},
                            'refresh': {'type': 'string'},
                        }
                    },
                    'message': {'type': 'string'},
                }
            }
        },
        description='Register a new user account'
    )
    def post(self, request):
        serializer = UserRegistrationSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()

            # Generate JWT tokens
            refresh = RefreshToken.for_user(user)

            return Response({
                'user': UserProfileSerializer(user).data,
                'tokens': {
                    'access': str(refresh.access_token),
                    'refresh': str(refresh),
                },
                'message': 'Account created successfully.'
            }, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
