from rest_framework import serializers
from users.models import User, Station
from tasks.models import Ticket, Task, Comment, CommentPhoto, TicketPhoto


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'username', 'first_name', 'last_name', 'role', 'station', 'telegram_id')
        read_only_fields = ('telegram_id',)


class StationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Station
        fields = ('id', 'name', 'manager')


class CommentPhotoSerializer(serializers.ModelSerializer):
    class Meta:
        model = CommentPhoto
        fields = ('id', 'image')


class CommentSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source='author.get_full_name', read_only=True)
    photos = CommentPhotoSerializer(many=True, read_only=True)

    class Meta:
        model = Comment
        fields = ('id', 'author', 'author_name', 'text', 'is_internal', 'photos', 'created_at')
        read_only_fields = ('author', 'created_at')


class TicketPhotoSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketPhoto
        fields = ('id', 'image')


class TaskSerializer(serializers.ModelSerializer):
    assigned_to_name = serializers.CharField(source='assigned_to.get_full_name', read_only=True)

    class Meta:
        model = Task
        fields = ('id', 'assigned_to', 'assigned_to_name', 'status', 'notes', 'started_at', 'finished_at')
        read_only_fields = ('started_at', 'finished_at')


class TicketSerializer(serializers.ModelSerializer):
    tasks = TaskSerializer(many=True, read_only=True)
    comments = serializers.SerializerMethodField()
    photos = TicketPhotoSerializer(many=True, read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)

    class Meta:
        model = Ticket
        fields = ('id', 'title', 'description', 'status', 'created_by', 'created_by_name',
                  'photos', 'tasks', 'comments', 'created_at', 'resolved_at')
        read_only_fields = ('created_by', 'created_at', 'resolved_at')

    def get_comments(self, obj):
        request = self.context.get('request')
        qs = obj.comments.prefetch_related('photos').all()
        if request and request.user.role == User.Role.WORKER:
            qs = qs.filter(is_internal=False)
        return CommentSerializer(qs, many=True, context=self.context).data


class TicketCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ticket
        fields = ('title', 'description')
