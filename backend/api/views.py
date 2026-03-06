from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from tasks.models import Task, Ticket, Comment
from users.models import User
from zammad_bridge.client import push_to_zammad
from .permissions import IsITWorker, IsStationManager, IsWorker
from .serializers import (
    TaskSerializer, TaskCreateSerializer,
    TicketSerializer, CommentSerializer, UserSerializer,
)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)


class TaskListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return TaskCreateSerializer
        return TaskSerializer

    def get_queryset(self):
        user = self.request.user
        if user.role == User.Role.WORKER:
            return Task.objects.filter(created_by=user)
        if user.role == User.Role.IT_WORKER:
            # See open tasks (to pick up) + tasks they already have a ticket in
            from django.db.models import Q
            return Task.objects.filter(
                Q(status=Task.Status.OPEN) | Q(tickets__assigned_to=user)
            ).distinct()
        # Admin and Station Manager see all
        return Task.objects.all()

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class TaskDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TaskSerializer

    def get_queryset(self):
        user = self.request.user
        if user.role == User.Role.WORKER:
            return Task.objects.filter(created_by=user)
        if user.role == User.Role.IT_WORKER:
            from django.db.models import Q
            return Task.objects.filter(
                Q(status=Task.Status.OPEN) | Q(tickets__assigned_to=user)
            ).distinct()
        return Task.objects.all()


class TaskResolveView(APIView):
    permission_classes = [IsAuthenticated, IsITWorker]

    def post(self, request, pk):
        try:
            task = Task.objects.filter(tickets__assigned_to=request.user).distinct().get(pk=pk)
        except Task.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if task.status == Task.Status.RESOLVED:
            return Response({'detail': 'Task already resolved.'}, status=status.HTTP_400_BAD_REQUEST)

        task.status = Task.Status.RESOLVED
        task.resolved_at = timezone.now()
        task.save()

        try:
            push_to_zammad(task)
        except Exception:
            pass  # zammad_synced stays False, retry via management command

        return Response(TaskSerializer(task).data)


class TicketCreateView(generics.CreateAPIView):
    permission_classes = [IsAuthenticated, IsITWorker]
    serializer_class = TicketSerializer

    def perform_create(self, serializer):
        task = generics.get_object_or_404(Task, pk=self.kwargs['task_pk'])
        serializer.save(task=task)


class TicketUpdateView(generics.UpdateAPIView):
    permission_classes = [IsAuthenticated, IsITWorker]
    serializer_class = TicketSerializer

    def get_queryset(self):
        return Ticket.objects.filter(assigned_to=self.request.user)

    def perform_update(self, serializer):
        ticket = self.get_object()
        new_status = serializer.validated_data.get('status', ticket.status)

        if new_status == Ticket.Status.IN_PROGRESS and not ticket.started_at:
            serializer.save(started_at=timezone.now())
        elif new_status == Ticket.Status.DONE and not ticket.finished_at:
            serializer.save(finished_at=timezone.now())
        else:
            serializer.save()


class CommentCreateView(generics.CreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CommentSerializer

    def perform_create(self, serializer):
        task = generics.get_object_or_404(Task, pk=self.kwargs['task_pk'])
        serializer.save(task=task, author=self.request.user)


class ITWorkerListView(APIView):
    permission_classes = [IsAuthenticated, IsITWorker]

    def get(self, request):
        workers = User.objects.filter(role=User.Role.IT_WORKER).exclude(pk=request.user.pk)
        data = [{'id': u.id, 'name': u.get_full_name() or u.username} for u in workers]
        return Response(data)


class StationWorkersView(APIView):
    permission_classes = [IsAuthenticated, IsStationManager]

    def _get_stations(self, user):
        from users.models import Station
        from django.db.models import Q
        return list(Station.objects.filter(Q(manager=user) | Q(deputies=user)).distinct())

    def get(self, request):
        stations = self._get_stations(request.user)
        if not stations:
            return Response({'detail': 'No station assigned.'}, status=status.HTTP_403_FORBIDDEN)
        station_ids = [s.id for s in stations]
        workers = User.objects.filter(station_id__in=station_ids, role=User.Role.WORKER)
        data = [{'id': u.id, 'username': u.username, 'name': u.get_full_name() or u.username, 'is_active': u.is_active, 'station': u.station.name if u.station else None} for u in workers]
        return Response(data)

    def post(self, request):
        stations = self._get_stations(request.user)
        if not stations:
            return Response({'detail': 'No station assigned.'}, status=status.HTTP_403_FORBIDDEN)
        # Use station_id from request if manager manages multiple, default to first
        station_id = request.data.get('station_id')
        if station_id:
            station = next((s for s in stations if s.id == int(station_id)), None)
            if not station:
                return Response({'detail': 'Station not found or not yours.'}, status=status.HTTP_403_FORBIDDEN)
        else:
            station = stations[0]

        username = request.data.get('username', '').strip()
        password = request.data.get('password', '').strip()
        first_name = request.data.get('first_name', '').strip()
        last_name = request.data.get('last_name', '').strip()

        if not username or not password:
            return Response({'detail': 'Username and password required.'}, status=status.HTTP_400_BAD_REQUEST)

        if User.objects.filter(username=username).exists():
            return Response({'detail': 'Username already taken.'}, status=status.HTTP_400_BAD_REQUEST)

        worker = User.objects.create_user(
            username=username,
            password=password,
            first_name=first_name,
            last_name=last_name,
            role=User.Role.WORKER,
            station=station,
        )
        return Response({'id': worker.id, 'username': worker.username, 'name': worker.get_full_name() or worker.username}, status=status.HTTP_201_CREATED)


class StationWorkerDeleteView(APIView):
    permission_classes = [IsAuthenticated, IsStationManager]

    def _get_stations(self, user):
        from users.models import Station
        from django.db.models import Q
        return list(Station.objects.filter(Q(manager=user) | Q(deputies=user)).distinct())

    def delete(self, request, pk):
        stations = self._get_stations(request.user)
        if not stations:
            return Response({'detail': 'No station assigned.'}, status=status.HTTP_403_FORBIDDEN)
        station_ids = [s.id for s in stations]

        try:
            worker = User.objects.get(pk=pk, station_id__in=station_ids, role=User.Role.WORKER)
        except User.DoesNotExist:
            return Response({'detail': 'Worker not found in your station.'}, status=status.HTTP_404_NOT_FOUND)

        worker.is_active = False
        worker.save(update_fields=['is_active'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        old_password = request.data.get('old_password', '')
        new_password = request.data.get('new_password', '')

        if not request.user.check_password(old_password):
            return Response({'detail': 'Current password is incorrect.'}, status=status.HTTP_400_BAD_REQUEST)

        if len(new_password) < 6:
            return Response({'detail': 'New password must be at least 6 characters.'}, status=status.HTTP_400_BAD_REQUEST)

        request.user.set_password(new_password)
        request.user.save()
        return Response({'detail': 'Password changed successfully.'})
