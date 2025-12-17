from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Category, Listing, Bid, Watchlist, Comment


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """Admin configuration for custom User model."""
    pass


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ('title', 'seller', 'starting_price', 'current_price', 'category', 'is_active', 'end_time')
    list_filter = ('is_active', 'category', 'created_at')
    search_fields = ('title', 'description', 'seller__username')
    date_hierarchy = 'created_at'


@admin.register(Bid)
class BidAdmin(admin.ModelAdmin):
    list_display = ('listing', 'bidder', 'amount', 'timestamp')
    list_filter = ('timestamp',)
    search_fields = ('listing__title', 'bidder__username')


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
