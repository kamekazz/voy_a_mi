from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import IntegrityError

from .models import User, Category, Listing, Bid, Watchlist, Comment
from .notifications import (
    send_outbid_notification,
    send_auction_won_notification,
    send_auction_ended_to_seller,
    send_auction_lost_notification,
)


def index(request):
    """Homepage displaying active listings."""
    listings = Listing.objects.filter(is_active=True).order_by('-created_at')
    categories = Category.objects.all()
    return render(request, "auctions/index.html", {
        "listings": listings,
        "categories": categories,
    })


def register_view(request):
    """User registration."""
    if request.method == "POST":
        username = request.POST["username"]
        email = request.POST["email"]
        password = request.POST["password"]
        confirmation = request.POST["confirmation"]

        # Ensure password matches confirmation
        if password != confirmation:
            messages.error(request, "Passwords must match.")
            return render(request, "auctions/register.html")

        # Attempt to create new user
        try:
            user = User.objects.create_user(username, email, password)
            user.save()
        except IntegrityError:
            messages.error(request, "Username already taken.")
            return render(request, "auctions/register.html")

        login(request, user)
        messages.success(request, "Account created successfully!")
        return redirect("index")

    return render(request, "auctions/register.html")


def login_view(request):
    """User login."""
    if request.method == "POST":
        username = request.POST["username"]
        password = request.POST["password"]
        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            messages.success(request, f"Welcome back, {username}!")
            return redirect("index")
        else:
            messages.error(request, "Invalid username and/or password.")
            return render(request, "auctions/login.html")

    return render(request, "auctions/login.html")


def logout_view(request):
    """User logout."""
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect("index")


@login_required
def profile_view(request):
    """User profile page."""
    return render(request, "auctions/profile.html")


def listing_detail(request, listing_id):
    """Display a single listing."""
    listing = get_object_or_404(Listing, pk=listing_id)
    is_watching = False
    if request.user.is_authenticated:
        is_watching = Watchlist.objects.filter(user=request.user, listing=listing).exists()

    return render(request, "auctions/listing.html", {
        "listing": listing,
        "is_watching": is_watching,
    })


@login_required
def create_listing(request):
    """Create a new auction listing."""
    categories = Category.objects.all()

    if request.method == "POST":
        title = request.POST["title"]
        description = request.POST["description"]
        starting_price = request.POST["starting_price"]
        category_id = request.POST.get("category")
        image = request.FILES.get("image")
        duration_days = int(request.POST.get("duration", 7))

        from django.utils import timezone
        from datetime import timedelta

        category = None
        if category_id:
            category = Category.objects.get(pk=category_id)

        listing = Listing(
            title=title,
            description=description,
            starting_price=starting_price,
            current_price=starting_price,
            category=category,
            seller=request.user,
            image=image,
            end_time=timezone.now() + timedelta(days=duration_days),
        )
        listing.save()

        messages.success(request, "Listing created successfully!")
        return redirect("listing_detail", listing_id=listing.id)

    return render(request, "auctions/create_listing.html", {
        "categories": categories,
    })


@login_required
def watchlist_view(request):
    """Display user's watchlist."""
    watchlist_items = Watchlist.objects.filter(user=request.user).select_related('listing')
    return render(request, "auctions/watchlist.html", {
        "watchlist_items": watchlist_items,
    })


@login_required
def toggle_watchlist(request, listing_id):
    """Add or remove a listing from watchlist."""
    listing = get_object_or_404(Listing, pk=listing_id)

    watchlist_item = Watchlist.objects.filter(user=request.user, listing=listing)
    if watchlist_item.exists():
        watchlist_item.delete()
        messages.info(request, "Removed from watchlist.")
    else:
        Watchlist.objects.create(user=request.user, listing=listing)
        messages.success(request, "Added to watchlist.")

    return redirect("listing_detail", listing_id=listing_id)


@login_required
def place_bid(request, listing_id):
    """Place a bid on a listing."""
    listing = get_object_or_404(Listing, pk=listing_id)

    if request.method == "POST":
        try:
            bid_amount = float(request.POST["bid_amount"])
        except (ValueError, KeyError):
            messages.error(request, "Invalid bid amount.")
            return redirect("listing_detail", listing_id=listing_id)

        # Check if auction is still active
        if not listing.is_active:
            messages.error(request, "This auction has ended.")
            return redirect("listing_detail", listing_id=listing_id)

        # Check if auction has expired
        if listing.is_expired():
            all_bidders = set(bid.bidder for bid in listing.bids.all())
            listing.close_auction()
            # Send notifications for auto-closed auction
            send_auction_ended_to_seller(listing)
            if listing.winner:
                send_auction_won_notification(listing.winner, listing)
                for bidder in all_bidders:
                    if bidder != listing.winner:
                        send_auction_lost_notification(bidder, listing)
            messages.error(request, "This auction has ended.")
            return redirect("listing_detail", listing_id=listing_id)

        # Check if user is the seller
        if listing.seller == request.user:
            messages.error(request, "You cannot bid on your own listing.")
            return redirect("listing_detail", listing_id=listing_id)

        # Check if bid is high enough
        if bid_amount <= float(listing.current_price):
            messages.error(request, f"Bid must be higher than ${listing.current_price}.")
            return redirect("listing_detail", listing_id=listing_id)

        # Get previous highest bidder before creating new bid
        previous_highest_bid = listing.bids.order_by('-amount').first()

        # Create the bid
        bid = Bid(listing=listing, bidder=request.user, amount=bid_amount)
        bid.save()

        # Update listing's current price
        listing.current_price = bid_amount
        listing.save()

        # Send outbid notification to previous highest bidder
        if previous_highest_bid and previous_highest_bid.bidder != request.user:
            send_outbid_notification(previous_highest_bid.bidder, listing, bid_amount)

        messages.success(request, f"Bid of ${bid_amount} placed successfully!")

    return redirect("listing_detail", listing_id=listing_id)


@login_required
def close_auction(request, listing_id):
    """Close an auction (seller only)."""
    listing = get_object_or_404(Listing, pk=listing_id)

    if listing.seller != request.user:
        messages.error(request, "You can only close your own auctions.")
        return redirect("listing_detail", listing_id=listing_id)

    # Get all bidders before closing
    all_bidders = set(bid.bidder for bid in listing.bids.all())

    listing.close_auction()

    # Send notifications
    send_auction_ended_to_seller(listing)

    if listing.winner:
        send_auction_won_notification(listing.winner, listing)
        # Notify losing bidders
        for bidder in all_bidders:
            if bidder != listing.winner:
                send_auction_lost_notification(bidder, listing)

    messages.success(request, "Auction closed successfully!")
    return redirect("listing_detail", listing_id=listing_id)


@login_required
def add_comment(request, listing_id):
    """Add a comment to a listing."""
    listing = get_object_or_404(Listing, pk=listing_id)

    if request.method == "POST":
        content = request.POST.get("content", "").strip()
        if content:
            Comment.objects.create(
                listing=listing,
                author=request.user,
                content=content
            )
            messages.success(request, "Comment added.")

    return redirect("listing_detail", listing_id=listing_id)
