from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q
from drf_spectacular.utils import extend_schema

from predictions.models import Position, Trade, Transaction
from predictions.api.serializers import (
    UserProfileSerializer,
    TradeSerializer,
    PositionSerializer,
    TransactionSerializer,
)


class UserProfileView(APIView):
    """
    API endpoint for user profile.

    GET /api/user/profile/ - Get user profile with balance
    PATCH /api/user/profile/ - Update profile (name, email)
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: UserProfileSerializer},
        description='Get current user profile with balance information'
    )
    def get(self, request):
        """GET /api/user/profile/"""
        serializer = UserProfileSerializer(request.user)
        return Response(serializer.data)

    @extend_schema(
        request=UserProfileSerializer,
        responses={200: UserProfileSerializer},
        description='Update user profile (first_name, last_name, email)'
    )
    def patch(self, request):
        """PATCH /api/user/profile/"""
        serializer = UserProfileSerializer(
            request.user,
            data=request.data,
            partial=True
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PortfolioView(APIView):
    """
    API endpoint for user portfolio.

    GET /api/user/portfolio/ - Get all positions with P&L summary
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: {'type': 'object'}},
        description='Get user portfolio with all positions and P&L summary'
    )
    def get(self, request):
        """GET /api/user/portfolio/"""
        positions = Position.objects.filter(
            user=request.user
        ).filter(
            Q(yes_quantity__gt=0) | Q(no_quantity__gt=0)
        ).select_related('market', 'market__event')

        total_unrealized = sum(p.total_unrealized_pnl for p in positions)
        total_realized = sum(p.realized_pnl for p in positions)

        return Response({
            'positions': PositionSerializer(
                positions,
                many=True,
                context={'request': request}
            ).data,
            'summary': {
                'balance': float(request.user.balance),
                'reserved_balance': float(request.user.reserved_balance),
                'available_balance': float(request.user.available_balance),
                'total_unrealized_pnl': float(total_unrealized),
                'total_realized_pnl': float(total_realized),
                'positions_count': positions.count(),
            }
        })


class UserTradesView(generics.ListAPIView):
    """
    API endpoint for user's trade history.

    GET /api/user/trades/ - List all trades where user is buyer or seller
    """
    permission_classes = [IsAuthenticated]
    serializer_class = TradeSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['market', 'contract_type', 'trade_type']

    def get_queryset(self):
        """Return trades where user is buyer or seller."""
        return Trade.objects.filter(
            Q(buyer=self.request.user) | Q(seller=self.request.user)
        ).select_related('market', 'market__event').order_by('-executed_at')


class UserTransactionsView(generics.ListAPIView):
    """
    API endpoint for user's transaction history.

    GET /api/user/transactions/ - List all balance transactions
    GET /api/user/transactions/?type=trade_buy - Filter by type
    """
    permission_classes = [IsAuthenticated]
    serializer_class = TransactionSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['type', 'market']

    def get_queryset(self):
        """Return user's transactions."""
        return Transaction.objects.filter(
            user=self.request.user
        ).select_related('market', 'order', 'trade').order_by('-created_at')
