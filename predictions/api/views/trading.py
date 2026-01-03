from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from decimal import Decimal
from drf_spectacular.utils import extend_schema

from predictions.models import Order, Position
from predictions.api.serializers import OrderSerializer


class OrderViewSet(viewsets.ModelViewSet):
    """
    API endpoint for user's orders.

    GET /api/orders/ - List user's orders (filterable by status, market)
    GET /api/orders/<id>/ - Get order detail
    DELETE /api/orders/<id>/ - Cancel order
    """
    permission_classes = [IsAuthenticated]
    serializer_class = OrderSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['status', 'market', 'side', 'contract_type']
    http_method_names = ['get', 'delete', 'head', 'options']  # No create/update via this endpoint

    def get_queryset(self):
        """Return only the user's orders."""
        return Order.objects.filter(
            user=self.request.user
        ).select_related('market', 'market__event').order_by('-created_at')

    @extend_schema(
        responses={200: {'type': 'object', 'properties': {'message': {'type': 'string'}}}},
        description='Cancel an order and refund reserved funds/shares'
    )
    def destroy(self, request, *args, **kwargs):
        """Cancel an order (DELETE /api/orders/<id>/)"""
        order = self.get_object()
        market = order.market

        # Only allow cancelling open or partially filled orders
        if order.status not in [Order.Status.OPEN, Order.Status.PARTIALLY_FILLED]:
            return Response({
                'error': 'order_not_cancellable',
                'message': "Order cannot be cancelled. Current status: " + order.get_status_display(),
            }, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        position, _ = Position.objects.get_or_create(user=user, market=market)

        # Calculate remaining quantity
        remaining_qty = order.quantity - order.filled_quantity

        if order.order_type == 'mint_set':
            # Refund reserved funds for mint request
            refund = Decimal(remaining_qty)
            user.reserved_balance -= refund
            user.balance += refund
            user.save()

        elif order.order_type == 'redeem_set':
            # Return reserved shares for redeem request
            position.reserved_yes_quantity -= remaining_qty
            position.yes_quantity += remaining_qty
            position.reserved_no_quantity -= remaining_qty
            position.no_quantity += remaining_qty
            position.save()

        elif order.side == 'buy':
            # Refund reserved funds for buy order
            refund_price = order.price if order.price is not None else Decimal('1.00')
            refund = refund_price * remaining_qty
            user.reserved_balance -= refund
            user.balance += refund
            user.save()

        elif order.side == 'sell':
            # Return reserved shares for sell order
            if order.contract_type == 'yes':
                position.reserved_yes_quantity -= remaining_qty
                position.yes_quantity += remaining_qty
            else:
                position.reserved_no_quantity -= remaining_qty
                position.no_quantity += remaining_qty
            position.save()

        order.status = Order.Status.CANCELLED
        order.save()

        return Response({
            'message': "Order cancelled successfully.",
            'order': OrderSerializer(order).data
        })
