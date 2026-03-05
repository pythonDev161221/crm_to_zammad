from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from tasks.models import Task, Ticket, Comment
from users.models import User
from zammad_bridge.client import push_to_zammad
from .permissions import IsITWorker, IsWorker
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
