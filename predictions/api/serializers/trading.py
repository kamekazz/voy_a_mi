from rest_framework import serializers
from decimal import Decimal
from predictions.models import Order, Trade, Position, Market
from .market import MarketListSerializer


class OrderSerializer(serializers.ModelSerializer):
    """Order serializer for display."""
    market_title = serializers.CharField(source='market.title', read_only=True)
    market_id = serializers.IntegerField(source='market.id', read_only=True)
    remaining_quantity = serializers.IntegerField(read_only=True)
    total_cost = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True
    )
    price_cents = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'id',
            'market_id',
            'market_title',
            'side',
            'contract_type',
            'order_type',
            'price',
            'price_cents',
            'quantity',
            'filled_quantity',
            'remaining_quantity',
            'status',
            'created_at',
            'updated_at',
        ]

    def get_price_cents(self, obj):
        """Convert price to cents for easier display."""
        if obj.price:
            return int(obj.price * 100)
        return None


class OrderCreateSerializer(serializers.Serializer):
    """Serializer for placing new orders."""
    side = serializers.ChoiceField(choices=['buy', 'sell'])
    contract_type = serializers.ChoiceField(choices=['yes', 'no'])
    order_type = serializers.ChoiceField(choices=['limit', 'market'], default='limit')
    price = serializers.IntegerField(min_value=1, max_value=99, required=False)
    quantity = serializers.IntegerField(min_value=1)

    def validate(self, data):
        """Validate order parameters."""
        if data['order_type'] == 'limit' and 'price' not in data:
            raise serializers.ValidationError({
                "price": "Price is required for limit orders."
            })
        if data['order_type'] == 'limit':
            price = data.get('price')
            if price is not None and (price < 1 or price > 99):
                raise serializers.ValidationError({
                    "price": "Price must be between 1 and 99 cents."
                })
        return data


class QuickOrderSerializer(serializers.Serializer):
    """Serializer for quick buy/sell (market orders by amount)."""
    action = serializers.ChoiceField(choices=['buy', 'sell'])
    contract_type = serializers.ChoiceField(choices=['yes', 'no'])
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.01'))

    def validate_amount(self, value):
        """Validate amount is positive."""
        if value <= 0:
            raise serializers.ValidationError("Amount must be greater than 0.")
        return value


class TradeSerializer(serializers.ModelSerializer):
    """Trade serializer."""
    market_title = serializers.CharField(source='market.title', read_only=True)
    market_id = serializers.IntegerField(source='market.id', read_only=True)
    is_buyer = serializers.SerializerMethodField()
    total_value = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True
    )

    class Meta:
        model = Trade
        fields = [
            'id',
            'market_id',
            'market_title',
            'contract_type',
            'price',
            'quantity',
            'trade_type',
            'total_value',
            'is_buyer',
            'executed_at',
        ]

    def get_is_buyer(self, obj):
        """Check if the requesting user is the buyer."""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.buyer_id == request.user.id
        return None


class PositionSerializer(serializers.ModelSerializer):
    """Position serializer with P&L calculations."""
    market = MarketListSerializer(read_only=True)
    unrealized_pnl_yes = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True
    )
    unrealized_pnl_no = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True
    )
    total_unrealized_pnl = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True
    )
    has_position = serializers.BooleanField(read_only=True)
    available_yes = serializers.SerializerMethodField()
    available_no = serializers.SerializerMethodField()

    class Meta:
        model = Position
        fields = [
            'id',
            'market',
            'yes_quantity',
            'no_quantity',
            'reserved_yes_quantity',
            'reserved_no_quantity',
            'available_yes',
            'available_no',
            'yes_avg_cost',
            'no_avg_cost',
            'unrealized_pnl_yes',
            'unrealized_pnl_no',
            'total_unrealized_pnl',
            'realized_pnl',
            'has_position',
        ]

    def get_available_yes(self, obj):
        """Available YES shares (not reserved)."""
        return obj.yes_quantity - obj.reserved_yes_quantity

    def get_available_no(self, obj):
        """Available NO shares (not reserved)."""
        return obj.no_quantity - obj.reserved_no_quantity


class PositionSummarySerializer(serializers.ModelSerializer):
    """Simplified position serializer for position endpoint."""
    market_id = serializers.IntegerField(source='market.id', read_only=True)
    available_yes = serializers.SerializerMethodField()
    available_no = serializers.SerializerMethodField()

    class Meta:
        model = Position
        fields = [
            'market_id',
            'yes_quantity',
            'no_quantity',
            'available_yes',
            'available_no',
            'yes_avg_cost',
            'no_avg_cost',
            'unrealized_pnl_yes',
            'unrealized_pnl_no',
            'total_unrealized_pnl',
            'realized_pnl',
        ]

    def get_available_yes(self, obj):
        return obj.yes_quantity - obj.reserved_yes_quantity

    def get_available_no(self, obj):
        return obj.no_quantity - obj.reserved_no_quantity


class MintRedeemSerializer(serializers.Serializer):
    """Serializer for mint/redeem complete set requests."""
    quantity = serializers.IntegerField(min_value=1)

    def validate_quantity(self, value):
        """Validate quantity is positive."""
        if value <= 0:
            raise serializers.ValidationError("Quantity must be at least 1.")
        return value


class OrderPreviewSerializer(serializers.Serializer):
    """Input serializer for order preview calculation."""
    action = serializers.ChoiceField(choices=['buy', 'sell'])
    contract_type = serializers.ChoiceField(choices=['yes', 'no'])
    order_type = serializers.ChoiceField(choices=['market', 'limit'])
    amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False
    )
    price = serializers.IntegerField(min_value=1, max_value=99, required=False)
    quantity = serializers.IntegerField(min_value=1, required=False)

    def validate(self, data):
        """Validate preview parameters."""
        order_type = data.get('order_type')
        action = data.get('action')

        if order_type == 'limit':
            if 'price' not in data:
                raise serializers.ValidationError({
                    "price": "Price is required for limit orders."
                })
            if 'quantity' not in data:
                raise serializers.ValidationError({
                    "quantity": "Quantity is required for limit orders."
                })
        elif order_type == 'market':
            if 'amount' not in data:
                raise serializers.ValidationError({
                    "amount": "Amount is required for market orders."
                })

        return data


class OrderPreviewResponseSerializer(serializers.Serializer):
    """Response serializer for order preview."""
    shares = serializers.IntegerField()
    avg_price = serializers.IntegerField()
    total_cost = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_proceeds = serializers.DecimalField(max_digits=10, decimal_places=2)
    potential_payout = serializers.DecimalField(max_digits=10, decimal_places=2)
    implied_probability = serializers.IntegerField()
    user_balance = serializers.DecimalField(max_digits=10, decimal_places=2)
    user_position = serializers.DictField()
    current_yes_price = serializers.IntegerField()
    current_no_price = serializers.IntegerField()
    warning = serializers.CharField(allow_null=True)
