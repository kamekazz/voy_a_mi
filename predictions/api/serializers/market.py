from rest_framework import serializers
from predictions.models import Category, Event, Market


class CategorySerializer(serializers.ModelSerializer):
    """Category serializer with event count."""
    event_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'description', 'icon', 'display_order', 'event_count']

    def get_event_count(self, obj):
        return obj.events.filter(status=Event.Status.ACTIVE).count()


class MarketListSerializer(serializers.ModelSerializer):
    """Compact market info for listings."""
    event_title = serializers.CharField(source='event.title', read_only=True)
    event_slug = serializers.CharField(source='event.slug', read_only=True)
    is_trading_active = serializers.BooleanField(read_only=True)
    thumbnail_url = serializers.SerializerMethodField()
    yes_probability = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        read_only=True
    )

    class Meta:
        model = Market
        fields = [
            'id',
            'title',
            'slug',
            'event_title',
            'event_slug',
            'status',
            'last_yes_price',
            'last_no_price',
            'total_volume',
            'is_trading_active',
            'yes_probability',
            'thumbnail_url',
        ]

    def get_thumbnail_url(self, obj):
        thumbnail = obj.display_thumbnail
        if thumbnail:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(thumbnail.url)
            return thumbnail.url
        return None


class MarketDetailSerializer(serializers.ModelSerializer):
    """Full market details with orderbook prices."""
    event_id = serializers.IntegerField(source='event.id', read_only=True)
    event_title = serializers.CharField(source='event.title', read_only=True)
    event_slug = serializers.CharField(source='event.slug', read_only=True)
    category_name = serializers.CharField(source='event.category.name', read_only=True)
    is_trading_active = serializers.BooleanField(read_only=True)
    spread = serializers.IntegerField(read_only=True)
    yes_probability = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        read_only=True
    )
    image_url = serializers.SerializerMethodField()
    trading_starts = serializers.DateTimeField(source='event.trading_starts', read_only=True)
    trading_ends = serializers.DateTimeField(source='event.trading_ends', read_only=True)
    resolution_source = serializers.CharField(source='event.resolution_source', read_only=True)

    class Meta:
        model = Market
        fields = [
            'id',
            'title',
            'slug',
            'description',
            'status',
            'event_id',
            'event_title',
            'event_slug',
            'category_name',
            'last_yes_price',
            'last_no_price',
            'best_yes_bid',
            'best_yes_ask',
            'best_no_bid',
            'best_no_ask',
            'total_volume',
            'volume_24h',
            'total_shares_outstanding',
            'fees_collected',
            'spread',
            'yes_probability',
            'is_trading_active',
            'image_url',
            'trading_starts',
            'trading_ends',
            'resolution_source',
            'created_at',
        ]

    def get_image_url(self, obj):
        image = obj.display_image
        if image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(image.url)
            return image.url
        return None


class EventListSerializer(serializers.ModelSerializer):
    """Event list serializer."""
    category_name = serializers.CharField(source='category.name', read_only=True, default=None)
    category_slug = serializers.CharField(source='category.slug', read_only=True, default=None)
    market_count = serializers.SerializerMethodField()
    is_trading_active = serializers.BooleanField(read_only=True)
    thumbnail_url = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = [
            'id',
            'title',
            'slug',
            'status',
            'event_type',
            'category_name',
            'category_slug',
            'trading_starts',
            'trading_ends',
            'resolution_date',
            'market_count',
            'is_trading_active',
            'thumbnail_url',
        ]

    def get_market_count(self, obj):
        return obj.markets.count()

    def get_thumbnail_url(self, obj):
        if obj.thumbnail:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.thumbnail.url)
            return obj.thumbnail.url
        return None


class EventDetailSerializer(serializers.ModelSerializer):
    """Full event detail with markets."""
    category = CategorySerializer(read_only=True)
    markets = MarketListSerializer(many=True, read_only=True)
    is_trading_active = serializers.BooleanField(read_only=True)
    time_remaining = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()
    created_by_username = serializers.CharField(source='created_by.username', read_only=True, default=None)

    class Meta:
        model = Event
        fields = [
            'id',
            'title',
            'slug',
            'description',
            'status',
            'event_type',
            'category',
            'resolution_source',
            'trading_starts',
            'trading_ends',
            'resolution_date',
            'is_trading_active',
            'time_remaining',
            'image_url',
            'markets',
            'created_by_username',
            'created_at',
        ]

    def get_time_remaining(self, obj):
        remaining = obj.time_remaining
        if remaining:
            return remaining.total_seconds()
        return None

    def get_image_url(self, obj):
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None
