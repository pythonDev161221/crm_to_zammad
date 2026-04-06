import logging

from django.conf import settings
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from tasks.models import Ticket, Task, TicketPhoto, CommentPhoto, EducationItem
from users.models import User, Station, StationInvite, RoleInvite
from zammad_bridge.agent_sync import sync_agent_created
from zammad_bridge.client import push_to_zammad
from .permissions import (
    IsITWorker, IsITOrSupplyWorker, IsITManager, IsITManagerOrDeputy,
    IsStationManager, IsStationManagerOrDeputy, IsWorker, IsWorkerOrStationManager,
)
from .serializers import (
    TicketSerializer, TicketCreateSerializer,
    TaskSerializer, CommentSerializer, UserSerializer,
    EducationItemSerializer,
)

logger = logging.getLogger(__name__)


def _user_dict(u):
    return {'id': u.id, 'username': u.username, 'name': u.get_full_name() or u.username, 'is_active': u.is_active}


def _get_managed_stations(user):
    return list(Station.objects.filter(Q(manager=user) | Q(deputies=user)).distinct())


def _get_tickets_for_user(user, qs):
    if user.role == User.Role.WORKER:
        return Ticket.objects.filter(created_by=user).filter(
            Q(status__in=[Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS]) |
            Q(status=Ticket.Status.RESOLVED, rating__isnull=True)
        )
    if user.role in (User.Role.STATION_MANAGER, User.Role.DEPUTY):
        station_ids = Station.objects.filter(
            Q(manager=user) | Q(deputies=user)
        ).values_list('id', flat=True)
        return qs.filter(station_id__in=station_ids)
    if user.role == User.Role.SUPPLY_WORKER:
        return qs.filter(tasks__assigned_to=user).exclude(tasks__status=Task.Status.CANCELLED).distinct()
    if user.role in (User.Role.IT_WORKER, User.Role.IT_MANAGER, User.Role.IT_DEPUTY):
        my_tasks = Task.objects.filter(ticket=OuterRef('pk'), assigned_to=user).exclude(status=Task.Status.CANCELLED)
        return qs.filter(
            Q(station__company__in=user.companies.all()) |
            Q(tasks__assigned_to=user, tasks__status__in=[Task.Status.OPEN, Task.Status.IN_PROGRESS, Task.Status.DONE])
        ).distinct().annotate(has_my_task=Exists(my_tasks)).order_by('-has_my_task', '-created_at')
    return qs  # admin: all non-resolved


def _build_invite_link(token):
    bot = getattr(settings, 'TELEGRAM_BOT_USERNAME', '')
    return f'https://t.me/{bot}?startapp=inv_{token}' if bot else None


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)

    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


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
        return _get_tickets_for_user(user, qs)

    def perform_create(self, serializer):
        user = self.request.user

        if user.role in (User.Role.STATION_MANAGER, User.Role.DEPUTY):
            stations = _get_managed_stations(user)
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
        return _get_tickets_for_user(user, qs)


class TicketResolveView(APIView):
    permission_classes = [IsAuthenticated, IsITWorker]

    def post(self, request, pk):
        try:
            ticket = Ticket.objects.filter(tasks__assigned_to=request.user).distinct().get(pk=pk)
        except Ticket.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if ticket.status == Ticket.Status.RESOLVED:
            return Response({'detail': 'Ticket already resolved.'}, status=status.HTTP_400_BAD_REQUEST)

        tasks = ticket.tasks.exclude(status=Task.Status.CANCELLED)
        if not tasks.exists() or tasks.exclude(status=Task.Status.DONE).exists():
            return Response({'detail': 'All tasks must be done before resolving.'}, status=status.HTTP_400_BAD_REQUEST)

        ticket.status = Ticket.Status.RESOLVED
        ticket.resolved_at = timezone.now()
        ticket.resolved_by = request.user
        ticket.save()

        try:
            push_to_zammad(ticket)
        except Exception as e:
            logger.warning(f'Zammad push failed for ticket #{ticket.pk}: {e}')
            # zammad_synced stays False, retry via management command

        return Response(TicketSerializer(ticket, context={'request': request}).data)


class TicketRateView(APIView):
    permission_classes = [IsAuthenticated, IsWorker]

    def post(self, request, pk):
        try:
            ticket = Ticket.objects.get(pk=pk, created_by=request.user, status=Ticket.Status.RESOLVED)
        except Ticket.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if ticket.rating is not None:
            return Response({'detail': 'Already rated.'}, status=status.HTTP_400_BAD_REQUEST)

        rating = request.data.get('rating')
        if rating is None or not isinstance(rating, int) or rating < 0 or rating > 5:
            return Response({'detail': 'Rating must be an integer from 0 to 5.'}, status=status.HTTP_400_BAD_REQUEST)

        ticket.rating = rating
        ticket.save(update_fields=['rating'])
        return Response({'detail': 'Rated successfully.'})


class TaskCreateView(generics.CreateAPIView):
    permission_classes = [IsAuthenticated, IsITWorker]
    serializer_class = TaskSerializer

    def perform_create(self, serializer):
        ticket = generics.get_object_or_404(Ticket, pk=self.kwargs['ticket_pk'])
        assigned_to = serializer.validated_data.get('assigned_to')
        ticket_company = ticket.created_by.station.company if ticket.created_by.station else None
        if ticket_company and not assigned_to.companies.filter(pk=ticket_company.pk).exists():
            raise DRFPermissionDenied('This IT worker is not assigned to this company.')
        serializer.save(ticket=ticket, created_by=self.request.user)


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


class TaskCancelView(generics.DestroyAPIView):
    permission_classes = [IsAuthenticated, IsITOrSupplyWorker]

    def get_queryset(self):
        return Task.objects.filter(
            Q(created_by=self.request.user) | Q(assigned_to=self.request.user)
        )

    def destroy(self, request, *args, **kwargs):
        task = self.get_object()
        if task.status == Task.Status.DONE:
            return Response({'detail': 'Cannot cancel a completed task.'}, status=status.HTTP_400_BAD_REQUEST)
        if task.status == Task.Status.CANCELLED:
            return Response({'detail': 'Task is already cancelled.'}, status=status.HTTP_400_BAD_REQUEST)
        task.status = Task.Status.CANCELLED
        task.save(update_fields=['status'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class CommentCreateView(generics.CreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CommentSerializer

    def perform_create(self, serializer):
        ticket = generics.get_object_or_404(Ticket, pk=self.kwargs['ticket_pk'])
        user = self.request.user
        is_internal = serializer.validated_data.get('is_internal', False)

        if user.role == User.Role.DEPUTY:
            raise DRFPermissionDenied('Deputies cannot post comments.')

        if user.role == User.Role.STATION_MANAGER:
            if ticket.status == Ticket.Status.RESOLVED:
                raise DRFPermissionDenied('Cannot comment on resolved tickets.')
            if not ticket.created_by.station_id or \
               ticket.created_by.station_id not in user.managed_stations.values_list('id', flat=True):
                raise DRFPermissionDenied('You can only comment on tickets from your station.')
            if is_internal:
                raise DRFPermissionDenied('Station managers cannot post internal comments.')

        if is_internal and user.role in (User.Role.WORKER, User.Role.SUPPLY_WORKER):
            raise DRFPermissionDenied('Workers cannot create internal comments.')

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

    def get(self, request):
        stations = _get_managed_stations(request.user)
        if not stations:
            return Response({'detail': 'No station assigned.'}, status=status.HTTP_403_FORBIDDEN)
        station_id = request.query_params.get('station_id')
        if station_id:
            station_ids = [s.id for s in stations if s.id == int(station_id)]
        else:
            station_ids = [s.id for s in stations]
        workers = User.objects.filter(station_id__in=station_ids, role=User.Role.WORKER)
        data = [
            {**_user_dict(u), 'station': u.station.name if u.station else None}
            for u in workers
        ]
        return Response(data)

    def post(self, request):
        stations = _get_managed_stations(request.user)
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
        return Response(_user_dict(worker), status=status.HTTP_201_CREATED)


class StationWorkerDeleteView(APIView):
    permission_classes = [IsAuthenticated, IsStationManagerOrDeputy]

    def delete(self, request, pk):
        stations = _get_managed_stations(request.user)
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
    permission_classes = [IsAuthenticated, IsITManagerOrDeputy]

    def get(self, request):
        companies = request.user.companies.all()
        return Response([{'id': c.id, 'name': c.name} for c in companies])


# ── IT Manager: manage company staff ──────────────────────────────────────────

def _resolve_manage_company(user, company_id=None):
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
        company_id = request.query_params.get('company_id')
        if company_id:
            companies = companies.filter(pk=company_id)
        qs = User.objects.filter(role=User.Role.IT_WORKER, companies__in=companies).distinct()
        return Response([_user_dict(u) for u in qs])

    def post(self, request):
        company = _resolve_manage_company(request.user, request.data.get('company_id'))
        worker = _create_managed_user(request.data, User.Role.IT_WORKER, company)
        try:
            sync_agent_created(worker)
        except Exception as e:
            logger.warning(f'Zammad agent sync failed for new IT worker {worker.username}: {e}')
        return Response(_user_dict(worker), status=status.HTTP_201_CREATED)


class ManageITWorkerDeleteView(APIView):
    permission_classes = [IsAuthenticated, IsITManager]

    def delete(self, request, pk):
        companies = request.user.companies.all()
        try:
            worker = User.objects.filter(pk=pk, role=User.Role.IT_WORKER, companies__in=companies).distinct().get()
        except User.DoesNotExist:
            return Response({'detail': 'IT worker not found in your companies.'}, status=status.HTTP_404_NOT_FOUND)
        worker.companies.remove(*companies)
        if not worker.companies.exists():
            worker.is_active = False
            worker.save(update_fields=['is_active'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ManageSupplyWorkersView(APIView):
    permission_classes = [IsAuthenticated, IsITManager]

    def get(self, request):
        companies = request.user.companies.all()
        company_id = request.query_params.get('company_id')
        if company_id:
            companies = companies.filter(pk=company_id)
        qs = User.objects.filter(role=User.Role.SUPPLY_WORKER, companies__in=companies).distinct()
        return Response([_user_dict(u) for u in qs])

    def post(self, request):
        company = _resolve_manage_company(request.user, request.data.get('company_id'))
        worker = _create_managed_user(request.data, User.Role.SUPPLY_WORKER, company)
        return Response(_user_dict(worker), status=status.HTTP_201_CREATED)


class ManageSupplyWorkerDeleteView(APIView):
    permission_classes = [IsAuthenticated, IsITManager]

    def delete(self, request, pk):
        companies = request.user.companies.all()
        try:
            worker = User.objects.filter(pk=pk, role=User.Role.SUPPLY_WORKER, companies__in=companies).distinct().get()
        except User.DoesNotExist:
            return Response({'detail': 'Supply worker not found in your companies.'}, status=status.HTTP_404_NOT_FOUND)
        worker.companies.remove(*companies)
        if not worker.companies.exists():
            worker.is_active = False
            worker.save(update_fields=['is_active'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ManageStationManagersView(APIView):
    permission_classes = [IsAuthenticated, IsITManagerOrDeputy]

    def _company_station_ids(self, user):
        return Station.objects.filter(company__in=user.companies.all()).values_list('id', flat=True)

    def get(self, request):
        companies = request.user.companies.all()
        company_id = request.query_params.get('company_id')
        if company_id:
            companies = companies.filter(pk=company_id)
        stations_qs = Station.objects.filter(company__in=companies)
        station_ids = stations_qs.values_list('id', flat=True)
        qs = User.objects.filter(
            role=User.Role.STATION_MANAGER
        ).filter(
            Q(managed_stations__id__in=station_ids) | Q(deputy_stations__id__in=station_ids)
        ).distinct()
        result = []
        for u in qs:
            managed = list(stations_qs.filter(manager=u).values('id', 'name'))
            result.append({
                'id': u.id,
                'username': u.username,
                'name': u.get_full_name() or u.username,
                'is_active': u.is_active,
                'stations': managed,
            })
        return Response(result)

    def post(self, request):
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
        return Response(_user_dict(manager), status=status.HTTP_201_CREATED)


class ManageStationManagerDeleteView(APIView):
    permission_classes = [IsAuthenticated, IsITManagerOrDeputy]

    def delete(self, request, pk):
        station_ids = ManageStationManagersView()._company_station_ids(request.user)
        try:
            manager = User.objects.filter(
                role=User.Role.STATION_MANAGER
            ).filter(
                Q(managed_stations__id__in=station_ids) | Q(deputy_stations__id__in=station_ids)
            ).distinct().get(pk=pk)
        except User.DoesNotExist:
            return Response(
                {'detail': 'Station manager not found in your companies.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        # Remove from stations belonging to this IT manager's companies
        stations_to_remove = Station.objects.filter(id__in=station_ids)
        for station in stations_to_remove:
            if station.manager_id == manager.pk:
                station.manager = None
                station.save(update_fields=['manager'])
            station.deputies.remove(manager)
        # Deactivate only if no managed or deputy stations remain anywhere
        still_manages = manager.managed_stations.exists() or manager.deputy_stations.exists()
        if not still_manages:
            manager.is_active = False
            manager.save(update_fields=['is_active'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ManageITDeputiesView(APIView):
    permission_classes = [IsAuthenticated, IsITManager]

    def get(self, request):
        companies = request.user.companies.all()
        qs = User.objects.filter(role=User.Role.IT_DEPUTY, companies__in=companies).distinct()
        return Response([_user_dict(u) for u in qs])

    def post(self, request):
        companies = list(request.user.companies.all())
        if not companies:
            return Response({'detail': 'No companies assigned.'}, status=status.HTTP_403_FORBIDDEN)
        worker_id = request.data.get('worker_id')
        if not worker_id:
            return Response({'detail': 'worker_id required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            worker = User.objects.filter(
                pk=worker_id, role=User.Role.IT_WORKER, companies__in=companies,
            ).distinct().get()
        except User.DoesNotExist:
            return Response({'detail': 'IT worker not found in your companies.'}, status=status.HTTP_404_NOT_FOUND)
        worker.role = User.Role.IT_DEPUTY
        worker.save(update_fields=['role'])
        return Response(_user_dict(worker), status=status.HTTP_200_OK)


class ManageITDeputyDemoteView(APIView):
    permission_classes = [IsAuthenticated, IsITManager]

    def delete(self, request, pk):
        companies = request.user.companies.all()
        try:
            deputy = User.objects.filter(pk=pk, role=User.Role.IT_DEPUTY, companies__in=companies).distinct().get()
        except User.DoesNotExist:
            return Response({'detail': 'IT deputy not found in your companies.'}, status=status.HTTP_404_NOT_FOUND)
        deputy.role = User.Role.IT_WORKER
        deputy.save(update_fields=['role'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ManageCompanyStationsView(APIView):
    """List stations in IT Manager's/IT Deputy's companies (for assigning station managers)."""
    permission_classes = [IsAuthenticated, IsITManagerOrDeputy]

    def get(self, request):
        companies = request.user.companies.all()
        company_id = request.query_params.get('company_id')
        if company_id:
            companies = companies.filter(pk=company_id)
        stations = Station.objects.filter(company__in=companies)
        if request.query_params.get('empty'):
            stations = stations.filter(manager__isnull=True)
        return Response([{'id': s.id, 'name': s.name} for s in stations])


class StationRemoveManagerView(APIView):
    permission_classes = [IsAuthenticated, IsITManagerOrDeputy]

    def delete(self, request, pk):
        companies = request.user.companies.all()
        try:
            station = Station.objects.get(pk=pk, company__in=companies)
        except Station.DoesNotExist:
            return Response({'detail': 'Station not found in your companies.'}, status=status.HTTP_404_NOT_FOUND)

        if station.manager is None:
            return Response({'detail': 'This station has no manager.'}, status=status.HTTP_400_BAD_REQUEST)

        manager = station.manager
        station.manager = None
        station.save(update_fields=['manager'])

        still_manages = manager.managed_stations.exists() or manager.deputy_stations.exists()
        if not still_manages:
            manager.is_active = False
            manager.save(update_fields=['is_active'])

        return Response(status=status.HTTP_204_NO_CONTENT)


class StationSetManagerView(APIView):
    permission_classes = [IsAuthenticated, IsITManagerOrDeputy]

    def post(self, request, pk):
        companies = request.user.companies.all()
        try:
            station = Station.objects.get(pk=pk, company__in=companies)
        except Station.DoesNotExist:
            return Response({'detail': 'Station not found in your companies.'}, status=status.HTTP_404_NOT_FOUND)

        user_id = request.data.get('user_id')
        if not user_id:
            return Response({'detail': 'user_id required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            manager = User.objects.filter(
                pk=user_id, role=User.Role.STATION_MANAGER, managed_stations__company__in=companies
            ).distinct().get()
        except User.DoesNotExist:
            return Response(
                {'detail': 'Station manager not found in your companies.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if station.manager is not None:
            return Response({'detail': 'This station already has a manager.'}, status=status.HTTP_400_BAD_REQUEST)

        station.manager = manager
        station.save(update_fields=['manager'])
        return Response({'detail': 'Manager assigned.'})


class RoleInviteView(APIView):
    permission_classes = [IsAuthenticated, IsITManager]

    def get(self, request):
        companies = request.user.companies.all()
        invites = RoleInvite.objects.filter(company__in=companies, is_used=False).select_related('company', 'station')
        return Response([{
            'id': i.id,
            'role': i.role,
            'company_id': i.company_id,
            'company_name': i.company.name,
            'station_id': i.station_id,
            'station_name': i.station.name if i.station else None,
            'token': i.token,
        } for i in invites])

    def post(self, request):
        role = request.data.get('role', '').strip()
        if role not in (RoleInvite.Role.IT_WORKER, RoleInvite.Role.SUPPLY_WORKER, RoleInvite.Role.STATION_MANAGER):
            raise ValidationError({'role': 'Invalid role.'})
        company = _resolve_manage_company(request.user, request.data.get('company_id'))
        station = None
        if role == RoleInvite.Role.STATION_MANAGER:
            station_id = request.data.get('station_id')
            if not station_id:
                raise ValidationError({'station_id': 'Station required for station manager invite.'})
            try:
                station = Station.objects.get(pk=station_id, company=company)
            except Station.DoesNotExist:
                raise ValidationError({'station_id': 'Station not found in your company.'})
        invite = RoleInvite.create(role=role, company=company, created_by=request.user, station=station)
        return Response(
            {'token': invite.token, 'link': _build_invite_link(invite.token)},
            status=status.HTTP_201_CREATED,
        )

    def delete(self, request, pk):
        companies = request.user.companies.all()
        try:
            invite = RoleInvite.objects.get(pk=pk, company__in=companies, is_used=False)
        except RoleInvite.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        invite.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class StationDeputiesView(APIView):
    permission_classes = [IsAuthenticated, IsStationManager]  # primary manager only

    def _primary_stations(self, user):
        return list(Station.objects.filter(manager=user))

    def get(self, request):
        stations = self._primary_stations(request.user)
        if not stations:
            return Response({'detail': 'No station assigned.'}, status=status.HTTP_403_FORBIDDEN)
        station_id = request.query_params.get('station_id')
        if station_id:
            station_ids = [s.id for s in stations if s.id == int(station_id)]
        else:
            station_ids = [s.id for s in stations]
        deputies = User.objects.filter(role=User.Role.DEPUTY, deputy_stations__id__in=station_ids).distinct()
        return Response([_user_dict(u) for u in deputies])

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
            return Response(_user_dict(worker), status=status.HTTP_201_CREATED)
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
            return Response(_user_dict(deputy), status=status.HTTP_201_CREATED)


class StationDeputyDeleteView(APIView):
    permission_classes = [IsAuthenticated, IsStationManager]

    def delete(self, request, pk):
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
        station_id = request.query_params.get('station_id')
        if station_id:
            demote_station = next((s for s in stations if s.id == int(station_id)), stations[0])
        else:
            demote_station = stations[0]
        deputy.role = User.Role.WORKER
        deputy.station = demote_station
        deputy.save(update_fields=['role', 'station'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class StationInviteView(APIView):
    permission_classes = [IsAuthenticated, IsStationManager]

    def _get_station(self, user, station_id=None):
        stations = list(Station.objects.filter(manager=user))
        if not stations:
            return None
        if station_id:
            return next((s for s in stations if s.id == int(station_id)), None)
        return stations[0]

    def get(self, request):
        station = self._get_station(request.user, request.query_params.get('station_id'))
        if not station:
            return Response({'detail': 'No station assigned.'}, status=status.HTTP_403_FORBIDDEN)
        invite = StationInvite.objects.filter(station=station, is_active=True).first()
        if not invite:
            return Response({'token': None, 'link': None})
        return Response({'token': invite.token, 'link': _build_invite_link(invite.token)})

    def post(self, request):
        station = self._get_station(request.user, request.data.get('station_id'))
        if not station:
            return Response({'detail': 'No station assigned.'}, status=status.HTTP_403_FORBIDDEN)
        invite = StationInvite.create_for_station(station, request.user)
        return Response(
            {'token': invite.token, 'link': _build_invite_link(invite.token)},
            status=status.HTTP_201_CREATED,
        )

    def delete(self, request):
        station = self._get_station(request.user, request.query_params.get('station_id'))
        if not station:
            return Response({'detail': 'No station assigned.'}, status=status.HTTP_403_FORBIDDEN)
        StationInvite.objects.filter(station=station, is_active=True).update(is_active=False)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MyStationsView(APIView):
    permission_classes = [IsAuthenticated, IsStationManagerOrDeputy]

    def get(self, request):
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
            return Response(
                {'detail': 'New password must be at least 6 characters.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        request.user.set_password(new_password)
        request.user.save()
        return Response({'detail': 'Password changed successfully.'})


# ── Education ─────────────────────────────────────────────────────────────────

def _education_company_ids(user):
    """Return list of company PKs the user can read education items from."""
    from users.models import Company
    if user.role == User.Role.ADMIN:
        return list(Company.objects.values_list('id', flat=True))
    if user.role in (User.Role.IT_WORKER, User.Role.IT_DEPUTY, User.Role.IT_MANAGER):
        return list(user.companies.values_list('id', flat=True))
    if user.role in (User.Role.STATION_MANAGER, User.Role.DEPUTY):
        return list(
            Station.objects.filter(Q(manager=user) | Q(deputies=user))
            .values_list('company_id', flat=True).distinct()
        )
    if user.role == User.Role.WORKER:
        if user.station and user.station.company_id:
            return [user.station.company_id]
    return []


class EducationListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role == User.Role.SUPPLY_WORKER:
            raise DRFPermissionDenied('Not available for supply workers.')
        company_ids = _education_company_ids(request.user)
        qs = EducationItem.objects.filter(company_id__in=company_ids).select_related('company', 'created_by')
        company_id = request.query_params.get('company_id')
        if company_id:
            qs = qs.filter(company_id=company_id)
        qs = qs.order_by('-created_at')
        return Response(EducationItemSerializer(qs, many=True, context={'request': request}).data)

    def post(self, request):
        user = request.user
        if user.role not in (User.Role.IT_WORKER, User.Role.IT_DEPUTY, User.Role.IT_MANAGER, User.Role.ADMIN):
            raise DRFPermissionDenied('Only IT staff can upload education materials.')

        title = request.data.get('title', '').strip()
        if not title:
            raise ValidationError({'title': 'Title is required.'})

        item_type = request.data.get('item_type', '').strip()
        if item_type not in (EducationItem.ItemType.FILE, EducationItem.ItemType.VIDEO_LINK):
            raise ValidationError({'item_type': 'Must be "file" or "video_link".'})

        company_id = request.data.get('company_id')
        allowed_ids = _education_company_ids(user)
        if not company_id:
            if len(allowed_ids) == 1:
                company_id = allowed_ids[0]
            else:
                raise ValidationError({'company_id': 'company_id is required.'})
        else:
            company_id = int(company_id)
            if company_id not in allowed_ids:
                raise DRFPermissionDenied('Company not in your scope.')

        from users.models import Company
        company = Company.objects.get(pk=company_id)
        description = request.data.get('description', '')
        file_obj = request.FILES.get('file')
        url = request.data.get('url', '').strip()

        if item_type == EducationItem.ItemType.FILE and not file_obj:
            raise ValidationError({'file': 'File is required for item_type "file".'})
        if item_type == EducationItem.ItemType.VIDEO_LINK and not url:
            raise ValidationError({'url': 'URL is required for item_type "video_link".'})

        item = EducationItem.objects.create(
            company=company,
            title=title,
            description=description,
            item_type=item_type,
            file=file_obj,
            url=url,
            created_by=user,
        )
        return Response(
            EducationItemSerializer(item, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )


class EducationDeleteView(APIView):
    permission_classes = [IsAuthenticated, IsITWorker]

    def delete(self, request, pk):
        allowed_ids = _education_company_ids(request.user)
        try:
            item = EducationItem.objects.get(pk=pk, company_id__in=allowed_ids)
        except EducationItem.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if item.file:
            item.file.delete(save=False)
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
