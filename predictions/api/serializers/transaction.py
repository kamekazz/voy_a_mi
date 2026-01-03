from rest_framework import serializers
from predictions.models import Transaction


class TransactionSerializer(serializers.ModelSerializer):
    """Transaction serializer for audit trail."""
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    market_title = serializers.CharField(source='market.title', read_only=True, default=None)
    market_id = serializers.IntegerField(source='market.id', read_only=True, default=None)

    class Meta:
        model = Transaction
        fields = [
            'id',
            'type',
            'type_display',
            'amount',
            'balance_before',
            'balance_after',
            'description',
            'market_id',
            'market_title',
            'order_id',
            'trade_id',
            'created_at',
        ]
        read_only_fields = fields
