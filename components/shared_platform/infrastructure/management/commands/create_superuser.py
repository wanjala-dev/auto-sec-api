import os
from django.core.management.base import BaseCommand
from django.conf import settings
from infrastructure.persistence.users.models import CustomUser

class Command(BaseCommand):
    help = 'Create or update a superuser.'

    def handle(self, *args, **options):
        password = getattr(settings, 'SUPER_USER_PASSWORD', None)
        if not password:
            self.stdout.write(self.style.ERROR('SUPER_USER_PASSWORD setting not found.'))
            return

        # Check if the superuser already exists
        user, created = CustomUser.objects.get_or_create(
            username='wanjala',
            defaults={
                'email': 'henry@wanjala.art',
                'is_verified': True
            }
        )

        if created:
            user.set_password(password)
            user.is_superuser = True
            user.is_staff = True
            user.is_admin = True
            user.save()
            self.stdout.write(self.style.SUCCESS('Superuser created successfully.'))
        else:
            # Update user properties if they already exist
            user.is_verified = True
            user.save()
            self.stdout.write(self.style.SUCCESS('Superuser updated successfully.'))
