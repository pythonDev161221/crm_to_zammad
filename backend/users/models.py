from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = 'admin', 'Admin'
        STATION_MANAGER = 'station_manager', 'Station Manager'
        IT_WORKER = 'it_worker', 'IT Worker'
        WORKER = 'worker', 'Worker'

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.WORKER)
    telegram_id = models.BigIntegerField(unique=True, null=True, blank=True)
    station = models.ForeignKey(
        'Station', on_delete=models.SET_NULL, null=True, blank=True, related_name='users'
    )

    def __str__(self):
        return f'{self.get_full_name() or self.username} ({self.role})'


class Station(models.Model):
    name = models.CharField(max_length=255)
    manager = models.OneToOneField(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='managed_station'
    )
    deputy = models.OneToOneField(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='deputy_station'
    )

    def is_managed_by(self, user):
        return user.pk in (
            self.manager_id,
            self.deputy_id,
        )

    def __str__(self):
        return self.name
