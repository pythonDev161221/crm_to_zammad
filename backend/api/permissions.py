from rest_framework.permissions import BasePermission
from users.models import User


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.role == User.Role.ADMIN


class IsITWorker(BasePermission):
    def has_permission(self, request, view):
        return request.user.role in (User.Role.IT_WORKER, User.Role.ADMIN)


class IsITOrSupplyWorker(BasePermission):
    def has_permission(self, request, view):
        return request.user.role in (User.Role.IT_WORKER, User.Role.SUPPLY_WORKER, User.Role.ADMIN)


class IsStationManager(BasePermission):
    def has_permission(self, request, view):
        return request.user.role in (User.Role.STATION_MANAGER, User.Role.ADMIN)


class IsWorker(BasePermission):
    def has_permission(self, request, view):
        return request.user.role == User.Role.WORKER


class IsWorkerOrStationManager(BasePermission):
    def has_permission(self, request, view):
        return request.user.role in (User.Role.WORKER, User.Role.STATION_MANAGER)
