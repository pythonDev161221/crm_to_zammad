from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from .models import User, Station, Company


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'full_name', 'role', 'station', 'telegram_id', 'is_active')
    list_filter = ('role', 'station', 'is_active')
    search_fields = ('username', 'first_name', 'last_name', 'telegram_id')
    fieldsets = UserAdmin.fieldsets + (
        ('CRM Info', {'fields': ('role', 'telegram_id', 'station', 'companies')}),
    )

    def get_changeform_initial_data(self, request):
        return {'is_active': False}

    @admin.display(description='Full Name')
    def full_name(self, obj):
        return obj.get_full_name() or '-'

    def save_model(self, request, obj, form, change):
        is_new = not change
        super().save_model(request, obj, form, change)

        if obj.role == User.Role.IT_WORKER and is_new:
            try:
                from zammad_bridge.agent_sync import sync_agent_created
                sync_agent_created(obj)
            except Exception as e:
                self.message_user(
                    request,
                    f'User saved, but Zammad agent sync failed: {e}',
                    level=messages.WARNING,
                )

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        obj = form.instance

        if obj.role == User.Role.IT_WORKER:
            try:
                from zammad_bridge.agent_sync import sync_agent_companies
                sync_agent_companies(obj)
            except Exception as e:
                self.message_user(
                    request,
                    f'User saved, but Zammad group sync failed: {e}',
                    level=messages.WARNING,
                )


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(Station)
class StationAdmin(admin.ModelAdmin):
    list_display = ('name', 'company', 'manager')
    list_filter = ('company',)
    search_fields = ('name',)
