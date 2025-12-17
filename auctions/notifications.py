from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string


def send_outbid_notification(previous_bidder, listing, new_bid_amount):
    """Send email notification when a user is outbid."""
    if not previous_bidder.email:
        return

    subject = f'You have been outbid on "{listing.title}"'
    message = f"""
Hello {previous_bidder.username},

You have been outbid on the auction "{listing.title}".

New highest bid: ${new_bid_amount}
Your bid: ${listing.current_price}

Visit the listing to place a new bid:
{settings.SITE_NAME}

Good luck!
"""
    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[previous_bidder.email],
        fail_silently=True,
    )


def send_auction_won_notification(winner, listing):
    """Send email notification when a user wins an auction."""
    if not winner.email:
        return

    subject = f'Congratulations! You won the auction for "{listing.title}"'
    message = f"""
Hello {winner.username},

Congratulations! You have won the auction for "{listing.title}".

Winning bid: ${listing.current_price}
Seller: {listing.seller.username}

Please proceed to checkout to complete your purchase.

Thank you for using {settings.SITE_NAME}!
"""
    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[winner.email],
        fail_silently=True,
    )


def send_auction_ended_to_seller(listing):
    """Send email notification to seller when their auction ends."""
    seller = listing.seller
    if not seller.email:
        return

    if listing.winner:
        subject = f'Your auction "{listing.title}" has ended - Item Sold!'
        message = f"""
Hello {seller.username},

Your auction "{listing.title}" has ended.

Final price: ${listing.current_price}
Winner: {listing.winner.username}

The buyer will be contacted to complete the purchase.

Thank you for selling on {settings.SITE_NAME}!
"""
    else:
        subject = f'Your auction "{listing.title}" has ended - No bids'
        message = f"""
Hello {seller.username},

Your auction "{listing.title}" has ended without any bids.

You may choose to relist the item if you wish.

Thank you for using {settings.SITE_NAME}!
"""

    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[seller.email],
        fail_silently=True,
    )


def send_auction_lost_notification(bidder, listing):
    """Send email to bidders who didn't win."""
    if not bidder.email:
        return

    subject = f'Auction ended: "{listing.title}"'
    message = f"""
Hello {bidder.username},

The auction for "{listing.title}" has ended.

Unfortunately, you did not win this auction.

Final price: ${listing.current_price}

Don't worry - there are many more great items available on {settings.SITE_NAME}!
"""
    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[bidder.email],
        fail_silently=True,
    )
