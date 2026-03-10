from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from tasks.models import Ticket, Task, Comment
from users.models import User, StationInvite
from zammad_bridge.client import push_to_zammad
from .permissions import IsITWorker, IsITOrSupplyWorker, IsITManager, IsStationManager, IsStationManagerOrDeputy, IsWorker, IsWorkerOrStationManager
from .serializers import (
    TicketSerializer, TicketCreateSerializer,
    TaskSerializer, CommentSerializer, UserSerializer,
)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)


class TicketListCreateView(generics.ListCreateAPIView):
    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated(), IsWorkerOrStationManager()]
        return [IsAuthenticated()]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return TicketCreateSerializer
        return TicketSerializer

    def get_queryset(self):
        user = self.request.user
        qs = Ticket.objects.exclude(status=Ticket.Status.RESOLVED)
        if user.role == User.Role.WORKER:
            return qs.filter(created_by=user)
        if user.role in (User.Role.STATION_MANAGER, User.Role.DEPUTY):
            from django.db.models import Q
            from users.models import Station
            station_ids = Station.objects.filter(
                Q(manager=user) | Q(deputies=user)
            ).values_list('id', flat=True)
            return qs.filter(station_id__in=station_ids)
        if user.role == User.Role.SUPPLY_WORKER:
            return qs.filter(tasks__assigned_to=user).distinct()
        if user.role in (User.Role.IT_WORKER, User.Role.IT_MANAGER):
            from django.db.models import Q
            user_companies = user.companies.all()
            return qs.filter(
                Q(station__company__in=user_companies) |
                Q(tasks__assigned_to=user)
            ).distinct()
        return qs  # admin: all non-resolved

    def perform_create(self, serializer):
        from tasks.models import TicketPhoto
        from users.models import Station
        from django.db.models import Q
        from rest_framework.exceptions import ValidationError, PermissionDenied as DRFPermissionDenied

        user = self.request.user

        if user.role in (User.Role.STATION_MANAGER, User.Role.DEPUTY):
            stations = list(Station.objects.filter(Q(manager=user) | Q(deputies=user)).distinct())
            if len(stations) == 1:
                station = stations[0]
            else:
                station_id = self.request.data.get('station_id')
                if not station_id:
                    raise ValidationError({'station_id': 'You manage multiple stations. Please provide station_id.'})
                station = next((s for s in stations if s.id == int(station_id)), None)
                if not station:
                    raise DRFPermissionDenied('Station not found or not yours.')
        else:
            station = user.station

        ticket = serializer.save(created_by=user, station=station)
        for photo in self.request.FILES.getlist('photos'):
            TicketPhoto.objects.create(ticket=ticket, image=photo)


class TicketDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TicketSerializer

    def get_queryset(self):
        user = self.request.user
        qs = Ticket.objects.exclude(status=Ticket.Status.RESOLVED)
        if user.role == User.Role.WORKER:
            return qs.filter(created_by=user)
        if user.role in (User.Role.STATION_MANAGER, User.Role.DEPUTY):
            from django.db.models import Q
            from users.models import Station
            station_ids = Station.objects.filter(
                Q(manager=user) | Q(deputies=user)
            ).values_list('id', flat=True)
            return qs.filter(station_id__in=station_ids)
        if user.role == User.Role.SUPPLY_WORKER:
            return qs.filter(tasks__assigned_to=user).distinct()
        if user.role in (User.Role.IT_WORKER, User.Role.IT_MANAGER):
            from django.db.models import Q
            user_companies = user.companies.all()
            return qs.filter(
                Q(station__company__in=user_companies) |
                Q(tasks__assigned_to=user)
            ).distinct()
        return qs  # admin: all non-resolved


class TicketResolveView(APIView):
    permission_classes = [IsAuthenticated, IsITWorker]

    def post(self, request, pk):
        try:
            ticket = Ticket.objects.filter(tasks__assigned_to=request.user).distinct().get(pk=pk)
        except Ticket.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if ticket.status == Ticket.Status.RESOLVED:
            return Response({'detail': 'Ticket already resolved.'}, status=status.HTTP_400_BAD_REQUEST)

        tasks = ticket.tasks.all()
        if not tasks.exists() or tasks.exclude(status=Task.Status.DONE).exists():
            return Response({'detail': 'All tasks must be done before resolving.'}, status=status.HTTP_400_BAD_REQUEST)

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
    permission_classes = [IsAuthenticated, IsITOrSupplyWorker]
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

        if user.role == User.Role.DEPUTY:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Deputies cannot post comments.')

        if user.role == User.Role.STATION_MANAGER:
            from rest_framework.exceptions import PermissionDenied
            if ticket.status == Ticket.Status.RESOLVED:
                raise PermissionDenied('Cannot comment on resolved tickets.')
            if not ticket.created_by.station_id or \
               ticket.created_by.station_id not in user.managed_stations.values_list('id', flat=True):
                raise PermissionDenied('You can only comment on tickets from your station.')
            if is_internal:
                raise PermissionDenied('Station managers cannot post internal comments.')

        if is_internal and user.role in (User.Role.WORKER, User.Role.SUPPLY_WORKER):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Workers cannot create internal comments.')

        comment = serializer.save(ticket=ticket, author=user)

        for photo in self.request.FILES.getlist('photos'):
            CommentPhoto.objects.create(comment=comment, image=photo)


class ITWorkerListView(APIView):
    permission_classes = [IsAuthenticated, IsITWorker]

    def get(self, request):
        ticket_id = request.query_params.get('ticket_id')  # filter by ticket's company
        qs = User.objects.filter(
            role__in=[User.Role.IT_WORKER, User.Role.IT_MANAGER, User.Role.SUPPLY_WORKER]
        ).exclude(pk=request.user.pk)
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
    permission_classes = [IsAuthenticated, IsStationManagerOrDeputy]

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
    permission_classes = [IsAuthenticated, IsStationManagerOrDeputy]

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


class MyCompaniesView(APIView):
    permission_classes = [IsAuthenticated, IsITManager]

    def get(self, request):
        companies = request.user.companies.all()
        return Response([{'id': c.id, 'name': c.name} for c in companies])


# ── IT Manager: manage company staff ──────────────────────────────────────────

def _resolve_manage_company(user, company_id=None):
    from rest_framework.exceptions import ValidationError, PermissionDenied as DRFPermissionDenied
    companies = list(user.companies.all())
    if not companies:
        raise DRFPermissionDenied('No companies assigned.')
    if company_id:
        company = next((c for c in companies if c.id == int(company_id)), None)
        if not company:
            raise DRFPermissionDenied('Company not found or not yours.')
        return company
    if len(companies) == 1:
        return companies[0]
    raise ValidationError({'company_id': 'You manage multiple companies. Please provide company_id.'})


def _create_managed_user(data, role, company):
    from rest_framework.exceptions import ValidationError
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    if not username or not password:
        raise ValidationError({'detail': 'Username and password required.'})
    if User.objects.filter(username=username).exists():
        raise ValidationError({'detail': 'Username already taken.'})
    new_user = User.objects.create_user(
        username=username,
        password=password,
        first_name=data.get('first_name', '').strip(),
        last_name=data.get('last_name', '').strip(),
        role=role,
    )
    new_user.companies.add(company)
    return new_user


class ManageITWorkersView(APIView):
    permission_classes = [IsAuthenticated, IsITManager]

    def get(self, request):
        companies = request.user.companies.all()
        qs = User.objects.filter(role=User.Role.IT_WORKER, companies__in=companies).distinct()
        return Response([{'id': u.id, 'username': u.username, 'name': u.get_full_name() or u.username, 'is_active': u.is_active} for u in qs])

    def post(self, request):
        company = _resolve_manage_company(request.user, request.data.get('company_id'))
        worker = _create_managed_user(request.data, User.Role.IT_WORKER, company)
        try:
            from zammad_bridge.agent_sync import sync_agent_created
            sync_agent_created(worker)
        except Exception:
            pass
        return Response({'id': worker.id, 'username': worker.username, 'name': worker.get_full_name() or worker.username}, status=status.HTTP_201_CREATED)


class ManageITWorkerDeleteView(APIView):
    permission_classes = [IsAuthenticated, IsITManager]

    def delete(self, request, pk):
        companies = request.user.companies.all()
        try:
            worker = User.objects.get(pk=pk, role=User.Role.IT_WORKER, companies__in=companies)
        except User.DoesNotExist:
            return Response({'detail': 'IT worker not found in your companies.'}, status=status.HTTP_404_NOT_FOUND)
        worker.is_active = False
        worker.save(update_fields=['is_active'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ManageSupplyWorkersView(APIView):
    permission_classes = [IsAuthenticated, IsITManager]

    def get(self, request):
        companies = request.user.companies.all()
        qs = User.objects.filter(role=User.Role.SUPPLY_WORKER, companies__in=companies).distinct()
        return Response([{'id': u.id, 'username': u.username, 'name': u.get_full_name() or u.username, 'is_active': u.is_active} for u in qs])

    def post(self, request):
        company = _resolve_manage_company(request.user, request.data.get('company_id'))
        worker = _create_managed_user(request.data, User.Role.SUPPLY_WORKER, company)
        return Response({'id': worker.id, 'username': worker.username, 'name': worker.get_full_name() or worker.username}, status=status.HTTP_201_CREATED)


class ManageSupplyWorkerDeleteView(APIView):
    permission_classes = [IsAuthenticated, IsITManager]

    def delete(self, request, pk):
        companies = request.user.companies.all()
        try:
            worker = User.objects.get(pk=pk, role=User.Role.SUPPLY_WORKER, companies__in=companies)
        except User.DoesNotExist:
            return Response({'detail': 'Supply worker not found in your companies.'}, status=status.HTTP_404_NOT_FOUND)
        worker.is_active = False
        worker.save(update_fields=['is_active'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ManageStationManagersView(APIView):
    permission_classes = [IsAuthenticated, IsITManager]

    def _company_station_ids(self, user):
        from users.models import Station
        return Station.objects.filter(company__in=user.companies.all()).values_list('id', flat=True)

    def get(self, request):
        from django.db.models import Q
        station_ids = self._company_station_ids(request.user)
        qs = User.objects.filter(
            role=User.Role.STATION_MANAGER
        ).filter(
            Q(managed_stations__id__in=station_ids) | Q(deputy_stations__id__in=station_ids)
        ).distinct()
        return Response([{'id': u.id, 'username': u.username, 'name': u.get_full_name() or u.username, 'is_active': u.is_active} for u in qs])

    def post(self, request):
        from users.models import Station
        companies = list(request.user.companies.all())
        if not companies:
            return Response({'detail': 'No companies assigned.'}, status=status.HTTP_403_FORBIDDEN)
        station_id = request.data.get('station_id')
        if not station_id:
            return Response({'detail': 'station_id required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            station = Station.objects.get(pk=station_id, company__in=companies)
        except Station.DoesNotExist:
            return Response({'detail': 'Station not found in your companies.'}, status=status.HTTP_404_NOT_FOUND)
        username = request.data.get('username', '').strip()
        password = request.data.get('password', '').strip()
        if not username or not password:
            return Response({'detail': 'Username and password required.'}, status=status.HTTP_400_BAD_REQUEST)
        if User.objects.filter(username=username).exists():
            return Response({'detail': 'Username already taken.'}, status=status.HTTP_400_BAD_REQUEST)
        manager = User.objects.create_user(
            username=username,
            password=password,
            first_name=request.data.get('first_name', '').strip(),
            last_name=request.data.get('last_name', '').strip(),
            role=User.Role.STATION_MANAGER,
        )
        if not station.manager:
            station.manager = manager
            station.save(update_fields=['manager'])
        else:
            station.deputies.add(manager)
        return Response({'id': manager.id, 'username': manager.username, 'name': manager.get_full_name() or manager.username}, status=status.HTTP_201_CREATED)


class ManageStationManagerDeleteView(APIView):
    permission_classes = [IsAuthenticated, IsITManager]

    def delete(self, request, pk):
        from django.db.models import Q
        station_ids = ManageStationManagersView()._company_station_ids(request.user)
        try:
            manager = User.objects.filter(
                role=User.Role.STATION_MANAGER
            ).filter(
                Q(managed_stations__id__in=station_ids) | Q(deputy_stations__id__in=station_ids)
            ).distinct().get(pk=pk)
        except User.DoesNotExist:
            return Response({'detail': 'Station manager not found in your companies.'}, status=status.HTTP_404_NOT_FOUND)
        manager.is_active = False
        manager.save(update_fields=['is_active'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ManageCompanyStationsView(APIView):
    """List stations in IT Manager's companies (for assigning station managers)."""
    permission_classes = [IsAuthenticated, IsITManager]

    def get(self, request):
        from users.models import Station
        stations = Station.objects.filter(company__in=request.user.companies.all())
        return Response([{'id': s.id, 'name': s.name} for s in stations])


class StationDeputiesView(APIView):
    permission_classes = [IsAuthenticated, IsStationManager]  # primary manager only

    def _primary_stations(self, user):
        from users.models import Station
        return list(Station.objects.filter(manager=user))

    def get(self, request):
        stations = self._primary_stations(request.user)
        if not stations:
            return Response({'detail': 'No station assigned.'}, status=status.HTTP_403_FORBIDDEN)
        station_ids = [s.id for s in stations]
        deputies = User.objects.filter(role=User.Role.DEPUTY, deputy_stations__id__in=station_ids).distinct()
        return Response([{'id': u.id, 'username': u.username, 'name': u.get_full_name() or u.username, 'is_active': u.is_active} for u in deputies])

    def post(self, request):
        stations = self._primary_stations(request.user)
        if not stations:
            return Response({'detail': 'No station assigned.'}, status=status.HTTP_403_FORBIDDEN)
        if len(stations) == 1:
            station = stations[0]
        else:
            station_id = request.data.get('station_id')
            if not station_id:
                return Response({'station_id': 'Please provide station_id.'}, status=status.HTTP_400_BAD_REQUEST)
            station = next((s for s in stations if s.id == int(station_id)), None)
            if not station:
                return Response({'detail': 'Station not found or not yours.'}, status=status.HTTP_403_FORBIDDEN)

        worker_id = request.data.get('worker_id')
        if worker_id:
            # Promote existing worker from this station
            try:
                worker = User.objects.get(pk=worker_id, role=User.Role.WORKER, station=station)
            except User.DoesNotExist:
                return Response({'detail': 'Worker not found in this station.'}, status=status.HTTP_404_NOT_FOUND)
            worker.role = User.Role.DEPUTY
            worker.station = None
            worker.save(update_fields=['role', 'station'])
            station.deputies.add(worker)
            return Response({'id': worker.id, 'username': worker.username, 'name': worker.get_full_name() or worker.username}, status=status.HTTP_201_CREATED)
        else:
            # Create new deputy
            username = request.data.get('username', '').strip()
            password = request.data.get('password', '').strip()
            if not username or not password:
                return Response({'detail': 'Username and password required.'}, status=status.HTTP_400_BAD_REQUEST)
            if User.objects.filter(username=username).exists():
                return Response({'detail': 'Username already taken.'}, status=status.HTTP_400_BAD_REQUEST)
            deputy = User.objects.create_user(
                username=username,
                password=password,
                first_name=request.data.get('first_name', '').strip(),
                last_name=request.data.get('last_name', '').strip(),
                role=User.Role.DEPUTY,
            )
            station.deputies.add(deputy)
            return Response({'id': deputy.id, 'username': deputy.username, 'name': deputy.get_full_name() or deputy.username}, status=status.HTTP_201_CREATED)


class StationDeputyDeleteView(APIView):
    permission_classes = [IsAuthenticated, IsStationManager]

    def delete(self, request, pk):
        from users.models import Station
        stations = list(Station.objects.filter(manager=request.user))
        if not stations:
            return Response({'detail': 'No station assigned.'}, status=status.HTTP_403_FORBIDDEN)
        station_ids = [s.id for s in stations]
        try:
            deputy = User.objects.get(pk=pk, role=User.Role.DEPUTY, deputy_stations__id__in=station_ids)
        except User.DoesNotExist:
            return Response({'detail': 'Deputy not found in your stations.'}, status=status.HTTP_404_NOT_FOUND)
        for station in stations:
            station.deputies.remove(deputy)
        deputy.is_active = False
        deputy.save(update_fields=['is_active'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class StationInviteView(APIView):
    permission_classes = [IsAuthenticated, IsStationManager]

    def _get_station(self, user, station_id=None):
        from users.models import Station
        stations = list(Station.objects.filter(manager=user))
        if not stations:
            return None
        if station_id:
            return next((s for s in stations if s.id == int(station_id)), None)
        return stations[0]

    def _build_link(self, token):
        from django.conf import settings
        bot = settings.TELEGRAM_BOT_USERNAME
        if bot:
            return f'https://t.me/{bot}?startapp=inv_{token}'
        return None

    def get(self, request):
        station = self._get_station(request.user, request.query_params.get('station_id'))
        if not station:
            return Response({'detail': 'No station assigned.'}, status=status.HTTP_403_FORBIDDEN)
        invite = StationInvite.objects.filter(station=station, is_active=True).first()
        if not invite:
            return Response({'token': None, 'link': None})
        return Response({'token': invite.token, 'link': self._build_link(invite.token)})

    def post(self, request):
        station = self._get_station(request.user, request.data.get('station_id'))
        if not station:
            return Response({'detail': 'No station assigned.'}, status=status.HTTP_403_FORBIDDEN)
        invite = StationInvite.create_for_station(station, request.user)
        return Response({'token': invite.token, 'link': self._build_link(invite.token)}, status=status.HTTP_201_CREATED)

    def delete(self, request):
        station = self._get_station(request.user, request.query_params.get('station_id'))
        if not station:
            return Response({'detail': 'No station assigned.'}, status=status.HTTP_403_FORBIDDEN)
        StationInvite.objects.filter(station=station, is_active=True).update(is_active=False)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MyStationsView(APIView):
    permission_classes = [IsAuthenticated, IsStationManagerOrDeputy]

    def get(self, request):
        from users.models import Station
        from django.db.models import Q
        stations = Station.objects.filter(
            Q(manager=request.user) | Q(deputies=request.user)
        ).distinct()
        return Response([{'id': s.id, 'name': s.name} for s in stations])


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
