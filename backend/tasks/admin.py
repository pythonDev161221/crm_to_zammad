from django.contrib import admin
from .models import Task, Ticket, Comment


class TicketInline(admin.TabularInline):
    model = Ticket
    extra = 0
    fields = ('assigned_to', 'status', 'notes', 'started_at', 'finished_at')
    readonly_fields = ('started_at', 'finished_at')


class CommentInline(admin.TabularInline):
    model = Comment
    extra = 0
    fields = ('author', 'text', 'created_at')
    readonly_fields = ('created_at',)


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ('title', 'created_by', 'status', 'zammad_synced', 'created_at', 'resolved_at')
    list_filter = ('status', 'zammad_synced')
    search_fields = ('title', 'description', 'created_by__username')
    readonly_fields = ('created_at', 'resolved_at', 'zammad_synced')
    inlines = [TicketInline, CommentInline]


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ('id', 'task', 'assigned_to', 'status', 'started_at', 'finished_at')
    list_filter = ('status',)
    search_fields = ('assigned_to__username', 'task__title')


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('id', 'task', 'author', 'created_at')
    search_fields = ('author__username', 'task__title')
