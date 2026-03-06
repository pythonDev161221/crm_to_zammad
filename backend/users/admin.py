from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Station, Company


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'full_name', 'role', 'station', 'telegram_id', 'is_active')
    list_filter = ('role', 'station', 'is_active')
    search_fields = ('username', 'first_name', 'last_name', 'telegram_id')
    fieldsets = UserAdmin.fieldsets + (
        ('CRM Info', {'fields': ('role', 'telegram_id', 'station')}),
    )

    @admin.display(description='Full Name')
    def full_name(self, obj):
        return obj.get_full_name() or '-'


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(Station)
class StationAdmin(admin.ModelAdmin):
    list_display = ('name', 'company', 'manager')
    list_filter = ('company',)
    search_fields = ('name',)
