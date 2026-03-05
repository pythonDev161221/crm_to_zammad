from rest_framework import serializers
from users.models import User, Station
from tasks.models import Task, Ticket, Comment


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'username', 'first_name', 'last_name', 'role', 'station', 'telegram_id')
        read_only_fields = ('telegram_id',)


class StationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Station
        fields = ('id', 'name', 'manager')


class CommentSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source='author.get_full_name', read_only=True)

    class Meta:
        model = Comment
        fields = ('id', 'author', 'author_name', 'text', 'created_at')
        read_only_fields = ('author', 'created_at')


class TicketSerializer(serializers.ModelSerializer):
    assigned_to_name = serializers.CharField(source='assigned_to.get_full_name', read_only=True)

    class Meta:
        model = Ticket
        fields = ('id', 'assigned_to', 'assigned_to_name', 'status', 'notes', 'started_at', 'finished_at')
        read_only_fields = ('started_at', 'finished_at')


class TaskSerializer(serializers.ModelSerializer):
    tickets = TicketSerializer(many=True, read_only=True)
    comments = CommentSerializer(many=True, read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)

    class Meta:
        model = Task
        fields = ('id', 'title', 'description', 'status', 'created_by', 'created_by_name',
                  'tickets', 'comments', 'created_at', 'resolved_at')
        read_only_fields = ('created_by', 'created_at', 'resolved_at')


class TaskCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = ('title', 'description')
