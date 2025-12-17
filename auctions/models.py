from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone


class User(AbstractUser):
    """Custom user model for the auction platform."""
    pass


class Category(models.Model):
    """Categories for organizing listings."""
    name = models.CharField(max_length=64)

    class Meta:
        verbose_name_plural = "Categories"

    def __str__(self):
        return self.name


class Listing(models.Model):
    """Auction listing representing an item for sale."""
    title = models.CharField(max_length=100)
    description = models.TextField()
    starting_price = models.DecimalField(max_digits=10, decimal_places=2)
    current_price = models.DecimalField(max_digits=10, decimal_places=2)
    image = models.ImageField(upload_to='listings/', blank=True, null=True)
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='listings'
    )
    seller = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='listings'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    end_time = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    winner = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='won_listings'
    )

    def __str__(self):
        return self.title

    def is_expired(self):
        """Check if the auction has ended."""
        return timezone.now() > self.end_time

    def close_auction(self):
        """Close the auction and set the winner."""
        if self.is_active:
            self.is_active = False
            highest_bid = self.bids.order_by('-amount').first()
            if highest_bid:
                self.winner = highest_bid.bidder
            self.save()


class Bid(models.Model):
    """A bid placed on a listing."""
    listing = models.ForeignKey(
        Listing,
        on_delete=models.CASCADE,
        related_name='bids'
    )
    bidder = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='bids'
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.bidder.username} bid ${self.amount} on {self.listing.title}"


class Watchlist(models.Model):
    """User's watchlist of listings they want to follow."""
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='watchlist'
    )
    listing = models.ForeignKey(
        Listing,
        on_delete=models.CASCADE,
        related_name='watchers'
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'listing')

    def __str__(self):
        return f"{self.user.username} watching {self.listing.title}"


class Comment(models.Model):
    """Comments/questions on a listing."""
    listing = models.ForeignKey(
        Listing,
        on_delete=models.CASCADE,
        related_name='comments'
    )
    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='comments'
    )
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Comment by {self.author.username} on {self.listing.title}"
