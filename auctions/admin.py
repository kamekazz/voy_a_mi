from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils import timezone
from .models import User, Category, Listing, Bid, Watchlist, Comment


# Admin Actions for Users
@admin.action(description="Activate selected users")
def activate_users(modeladmin, request, queryset):
    queryset.update(is_active=True)


@admin.action(description="Deactivate selected users")
def deactivate_users(modeladmin, request, queryset):
    queryset.update(is_active=False)


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """Admin configuration for custom User model."""
    actions = [activate_users, deactivate_users]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


# Admin Actions for Listings
@admin.action(description="Close selected auctions")
def close_auctions(modeladmin, request, queryset):
    for listing in queryset.filter(is_active=True):
        listing.close_auction()


@admin.action(description="Reopen selected auctions")
def reopen_auctions(modeladmin, request, queryset):
    queryset.update(is_active=True)


@admin.action(description="Close all expired auctions")
def close_expired_auctions(modeladmin, request, queryset):
    expired = queryset.filter(is_active=True, end_time__lt=timezone.now())
    for listing in expired:
        listing.close_auction()


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ('title', 'seller', 'starting_price', 'current_price', 'category', 'is_active', 'end_time', 'winner')
    list_filter = ('is_active', 'category', 'created_at')
    search_fields = ('title', 'description', 'seller__username')
    date_hierarchy = 'created_at'
    actions = [close_auctions, reopen_auctions, close_expired_auctions]
    readonly_fields = ('created_at',)


# Admin Action for Bids
@admin.action(description="Delete bids and recalculate listing prices")
def delete_bids_recalculate(modeladmin, request, queryset):
    listings_affected = set()
    for bid in queryset:
        listings_affected.add(bid.listing)
        bid.delete()

    for listing in listings_affected:
        highest_bid = listing.bids.order_by('-amount').first()
        if highest_bid:
            listing.current_price = highest_bid.amount
        else:
            listing.current_price = listing.starting_price
        listing.save()


@admin.register(Bid)
class BidAdmin(admin.ModelAdmin):
    list_display = ('listing', 'bidder', 'amount', 'timestamp')
    list_filter = ('timestamp',)
    search_fields = ('listing__title', 'bidder__username')
    actions = [delete_bids_recalculate]


@admin.register(Watchlist)
class WatchlistAdmin(admin.ModelAdmin):
    list_display = ('user', 'listing', 'added_at')
    list_filter = ('added_at',)
    search_fields = ('user__username', 'listing__title')


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('listing', 'author', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('listing__title', 'author__username', 'content')
