from django.db import models
from django.conf import settings

# Create your models here.
# https://levelup.gitconnected.com/building-a-membership-system-in-django-under-5-mins-5efd7e03627d
MEMBERSHIP_CHOICES = (
    ('Premium', 'pre'),
    ('Free', 'free'),
)
class Membership(models.Model):
    slug = models.SlugField(null=True, blank=True)
    membership_type = models.CharField(
        choices=MEMBERSHIP_CHOICES,
        default='Free',
        max_length=30,
    )
    price = models.DecimalField(default=0, max_digits=10, decimal_places=2)

    def __str__(self):
        return self.membership_type

    class Meta:
        app_label = "membership"


class UserMembership(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        related_name='user_membership',
        on_delete=models.CASCADE,
    )
    membership = models.ForeignKey(
        Membership,
        related_name='user_membership',
        on_delete=models.SET_NULL,
        null=True,
    )

    def __str__(self):
        return self.user.username

    class Meta:
        app_label = "membership"


class Subscription(models.Model):
    user_membership = models.ForeignKey(
        UserMembership,
        related_name='subscription',
        on_delete=models.CASCADE,
    )
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.user_membership.user.username

    class Meta:
        app_label = "membership"
