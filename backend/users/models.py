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
    companies = models.ManyToManyField(
        'Company', blank=True, related_name='it_workers'
    )

    def __str__(self):
        return f'{self.get_full_name() or self.username} ({self.role})'


class Company(models.Model):
    name = models.CharField(max_length=255)

    def __str__(self):
        return self.name


class Station(models.Model):
    name = models.CharField(max_length=255)
    company = models.ForeignKey(
        Company, on_delete=models.SET_NULL, null=True, blank=True, related_name='stations'
    )
    manager = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='managed_stations'
    )
    deputies = models.ManyToManyField(
        User, blank=True, related_name='deputy_stations'
    )

    def is_managed_by(self, user):
        if self.manager_id == user.pk:
            return True
        return self.deputies.filter(pk=user.pk).exists()

    def __str__(self):
        return self.name
