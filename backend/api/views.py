from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from tasks.models import Ticket, Task, Comment
from users.models import User
from zammad_bridge.client import push_to_zammad
from .permissions import IsITWorker, IsStationManager, IsWorker
from .serializers import (
    TicketSerializer, TicketCreateSerializer,
    TaskSerializer, CommentSerializer, UserSerializer,
)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)


class TicketListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return TicketCreateSerializer
        return TicketSerializer

    def get_queryset(self):
        user = self.request.user
        if user.role == User.Role.WORKER:
            return Ticket.objects.filter(created_by=user)
        if user.role == User.Role.IT_WORKER:
            from django.db.models import Q
            user_companies = user.companies.all()
            return Ticket.objects.filter(
                Q(status=Ticket.Status.OPEN, created_by__station__company__in=user_companies) |
                Q(tasks__assigned_to=user)
            ).distinct()
        return Ticket.objects.all()

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class TicketDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TicketSerializer

    def get_queryset(self):
        user = self.request.user
        if user.role == User.Role.WORKER:
            return Ticket.objects.filter(created_by=user)
        if user.role == User.Role.IT_WORKER:
            from django.db.models import Q
            user_companies = user.companies.all()
            return Ticket.objects.filter(
                Q(status=Ticket.Status.OPEN, created_by__station__company__in=user_companies) |
                Q(tasks__assigned_to=user)
            ).distinct()
        return Ticket.objects.all()


class TicketResolveView(APIView):
    permission_classes = [IsAuthenticated, IsITWorker]

    def post(self, request, pk):
        try:
            ticket = Ticket.objects.filter(tasks__assigned_to=request.user).distinct().get(pk=pk)
        except Ticket.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if ticket.status == Ticket.Status.RESOLVED:
            return Response({'detail': 'Ticket already resolved.'}, status=status.HTTP_400_BAD_REQUEST)

        ticket.status = Ticket.Status.RESOLVED
        ticket.resolved_at = timezone.now()
        ticket.save()

        try:
            push_to_zammad(ticket)
        except Exception:
            pass  # zammad_synced stays False, retry via management command

        return Response(TicketSerializer(ticket).data)


class TaskCreateView(generics.CreateAPIView):
    permission_classes = [IsAuthenticated, IsITWorker]
    serializer_class = TaskSerializer

    def perform_create(self, serializer):
        ticket = generics.get_object_or_404(Ticket, pk=self.kwargs['ticket_pk'])
        assigned_to = serializer.validated_data.get('assigned_to')
        ticket_company = ticket.created_by.station.company if ticket.created_by.station else None
        if ticket_company and not assigned_to.companies.filter(pk=ticket_company.pk).exists():
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('This IT worker is not assigned to this company.')
        serializer.save(ticket=ticket)


class TaskUpdateView(generics.UpdateAPIView):
    permission_classes = [IsAuthenticated, IsITWorker]
    serializer_class = TaskSerializer

    def get_queryset(self):
        return Task.objects.filter(assigned_to=self.request.user)

    def perform_update(self, serializer):
        task = self.get_object()
        new_status = serializer.validated_data.get('status', task.status)

        if new_status == Task.Status.IN_PROGRESS and not task.started_at:
            serializer.save(started_at=timezone.now())
        elif new_status == Task.Status.DONE and not task.finished_at:
            serializer.save(finished_at=timezone.now())
        else:
            serializer.save()


class CommentCreateView(generics.CreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CommentSerializer

    def perform_create(self, serializer):
        from tasks.models import CommentPhoto
        ticket = generics.get_object_or_404(Ticket, pk=self.kwargs['ticket_pk'])
        user = self.request.user
        is_internal = serializer.validated_data.get('is_internal', False)

        if is_internal and user.role == User.Role.WORKER:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Workers cannot create internal comments.')

        comment = serializer.save(ticket=ticket, author=user)

        for photo in self.request.FILES.getlist('photos'):
            CommentPhoto.objects.create(comment=comment, image=photo)


class ITWorkerListView(APIView):
    permission_classes = [IsAuthenticated, IsITWorker]

    def get(self, request):
        ticket_id = request.query_params.get('ticket_id')  # filter by ticket's company
        qs = User.objects.filter(role=User.Role.IT_WORKER).exclude(pk=request.user.pk)
        if ticket_id:
            try:
                ticket = Ticket.objects.get(pk=ticket_id)
                ticket_company = ticket.created_by.station.company if ticket.created_by.station else None
                if ticket_company:
                    qs = qs.filter(companies=ticket_company)
                else:
                    qs = qs.none()
            except Ticket.DoesNotExist:
                qs = qs.none()
        else:
            qs = qs.filter(companies__isnull=False).distinct()
        data = [{'id': u.id, 'name': u.get_full_name() or u.username} for u in qs]
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
