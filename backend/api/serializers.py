from django.db.models import Q
from rest_framework import serializers
from users.models import User, Station
from tasks.models import Ticket, Task, Comment, CommentPhoto, TicketPhoto


class UserSerializer(serializers.ModelSerializer):
    station_name = serializers.SerializerMethodField()
    company_names = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'id', 'username', 'first_name', 'last_name', 'role',
            'station', 'station_name', 'company_names', 'telegram_id', 'phone',
        )
        read_only_fields = ('telegram_id', 'station_name', 'company_names')

    def _managed_stations(self, obj):
        return Station.objects.filter(Q(manager=obj) | Q(deputies=obj)).distinct()

    def get_station_name(self, obj):
        # Station managers/deputies: show all stations they manage
        if obj.role in (User.Role.STATION_MANAGER, User.Role.DEPUTY):
            names = list(self._managed_stations(obj).values_list('name', flat=True))
            return ', '.join(names) if names else None
        # Workers: their own station
        return obj.station.name if obj.station else None

    def get_company_names(self, obj):
        # IT workers/managers: from M2M companies
        if obj.companies.exists():
            return [c.name for c in obj.companies.all()]
        # Station managers/deputies: from their managed stations' companies
        if obj.role in (User.Role.STATION_MANAGER, User.Role.DEPUTY):
            companies = set(
                s.company.name for s in self._managed_stations(obj).select_related('company') if s.company
            )
            return list(companies)
        # Workers: from their station's company
        if obj.station and obj.station.company:
            return [obj.station.company.name]
        return []


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
    created_by_phone = serializers.CharField(source='created_by.phone', read_only=True)
    station_name = serializers.CharField(source='station.name', default=None, read_only=True)
    company_name = serializers.CharField(source='station.company.name', default=None, read_only=True)

    class Meta:
        model = Ticket
        fields = ('id', 'title', 'description', 'status', 'created_by', 'created_by_name',
                  'created_by_phone', 'station_name', 'company_name', 'photos', 'tasks',
                  'comments', 'created_at', 'resolved_at', 'rating')
        read_only_fields = ('created_by', 'created_at', 'resolved_at', 'rating')

    def get_comments(self, obj):
        request = self.context.get('request')
        qs = obj.comments.prefetch_related('photos').all()
        non_it_roles = (User.Role.WORKER, User.Role.SUPPLY_WORKER, User.Role.STATION_MANAGER, User.Role.DEPUTY)
        if request and request.user.role in non_it_roles:
            qs = qs.filter(is_internal=False)
        return CommentSerializer(qs, many=True, context=self.context).data


class TicketCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ticket
        fields = ('title', 'description')
