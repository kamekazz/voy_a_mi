from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from decimal import Decimal


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_preferences(sender, instance, created, **kwargs):
    """Auto-create UserPreferences when a new user is created."""
    from .models import UserPreferences
    if created:
        UserPreferences.objects.get_or_create(user=instance)


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def award_registration_bonus(sender, instance, created, **kwargs):
    """Award 500 tokens to new users upon registration."""
    from .models import Transaction

    if created:
        # Award 500 tokens as registration bonus
        bonus_amount = Decimal('500.00')
        instance.tokens = bonus_amount
        instance.save(update_fields=['tokens'])

        # Create transaction record
        Transaction.objects.create(
            user=instance,
            type=Transaction.Type.EVENT_REWARD,
            amount=bonus_amount,
            tokens_before=Decimal('0.00'),
            tokens_after=bonus_amount,
            description='Registration bonus: Welcome to Voy a Mi!'
        )
