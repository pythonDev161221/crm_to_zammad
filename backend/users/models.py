import secrets

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = 'admin', 'Admin'
        STATION_MANAGER = 'station_manager', 'Station Manager'
        DEPUTY = 'deputy', 'Deputy'
        IT_MANAGER = 'it_manager', 'IT Manager'
        IT_DEPUTY = 'it_deputy', 'IT Deputy'
        IT_WORKER = 'it_worker', 'IT Worker'
        SUPPLY_WORKER = 'supply_worker', 'Supply Worker'
        WORKER = 'worker', 'Worker'

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.WORKER)
    telegram_id = models.BigIntegerField(unique=True, null=True, blank=True)
    phone = models.CharField(max_length=30, blank=True, default='')
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


class StationInvite(models.Model):
    token = models.CharField(max_length=64, unique=True)
    station = models.ForeignKey(Station, on_delete=models.CASCADE, related_name='invites')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_invites')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @classmethod
    def create_for_station(cls, station, created_by):
        cls.objects.filter(station=station, is_active=True).update(is_active=False)
        return cls.objects.create(
            token=secrets.token_urlsafe(32),
            station=station,
            created_by=created_by,
        )

    def __str__(self):
        return f'Invite for {self.station} (active={self.is_active})'


class RoleInvite(models.Model):
    class Role(models.TextChoices):
        IT_MANAGER = 'it_manager', 'IT Manager'
        IT_WORKER = 'it_worker', 'IT Worker'
        SUPPLY_WORKER = 'supply_worker', 'Supply Worker'
        STATION_MANAGER = 'station_manager', 'Station Manager'

    token = models.CharField(max_length=64, unique=True)
    role = models.CharField(max_length=20, choices=Role.choices)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='role_invites')
    station = models.ForeignKey(Station, on_delete=models.SET_NULL, null=True, blank=True, related_name='role_invites')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_role_invites')
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    @classmethod
    def create(cls, role, company, created_by, station=None):
        return cls.objects.create(
            token=secrets.token_urlsafe(32),
            role=role,
            company=company,
            station=station,
            created_by=created_by,
        )

    def __str__(self):
        return f'RoleInvite {self.role} @ {self.company} (used={self.is_used})'
