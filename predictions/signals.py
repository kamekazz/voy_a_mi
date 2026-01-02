from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_preferences(sender, instance, created, **kwargs):
    """Auto-create UserPreferences when a new user is created."""
    from .models import UserPreferences
    if created:
        UserPreferences.objects.get_or_create(user=instance)
