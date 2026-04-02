from django.test import TestCase
from rest_framework.test import APITestCase
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import User, Station, Company
from tasks.models import Ticket, Task, Comment


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_user(username, role, station=None, companies=None, **kwargs):
    u = User.objects.create_user(username=username, password='pass1234', role=role, station=station, **kwargs)
    if companies:
        u.companies.set(companies)
    return u


def auth(client, user):
    token = RefreshToken.for_user(user).access_token
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')


class BaseSetup(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Shell')
        self.station = Station.objects.create(name='AZS-1', company=self.company)

        self.admin = make_user('admin', User.Role.ADMIN)
        self.manager = make_user('manager', User.Role.STATION_MANAGER)
        self.station.manager = self.manager
        self.station.save()

        self.it1 = make_user('it1', User.Role.IT_WORKER, companies=[self.company])
        self.it2 = make_user('it2', User.Role.IT_WORKER, companies=[self.company])
        self.it_no_company = make_user('it_none', User.Role.IT_WORKER)

        self.worker = make_user('worker1', User.Role.WORKER, station=self.station)
        self.worker2 = make_user('worker2', User.Role.WORKER, station=self.station)

    def make_ticket(self, created_by=None):
        user = created_by or self.worker
        return Ticket.objects.create(
            created_by=user,
            station=user.station,
            title='Printer broken',
            description='Does not print',
        )

    def make_task(self, ticket, assigned_to=None):
        return Task.objects.create(
            ticket=ticket,
            assigned_to=assigned_to or self.it1,
        )


# ── Auth ──────────────────────────────────────────────────────────────────────

class AuthTests(APITestCase):
    def test_unauthenticated_request_rejected(self):
        res = self.client.get('/api/tickets/')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_authenticated_request_allowed(self):
        user = make_user('u', User.Role.WORKER)
        auth(self.client, user)
        res = self.client.get('/api/tickets/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)


# ── Ticket List / Create ──────────────────────────────────────────────────────

class TicketListTests(BaseSetup):
    def test_worker_sees_only_own_tickets(self):
        t1 = self.make_ticket(self.worker)
        t2 = self.make_ticket(self.worker2)
        auth(self.client, self.worker)
        res = self.client.get('/api/tickets/')
        ids = [t['id'] for t in res.data]
        self.assertIn(t1.id, ids)
        self.assertNotIn(t2.id, ids)

    def test_it_worker_sees_open_tickets_from_their_company(self):
        ticket = self.make_ticket(self.worker)
        auth(self.client, self.it1)
        res = self.client.get('/api/tickets/')
        ids = [t['id'] for t in res.data]
        self.assertIn(ticket.id, ids)

    def test_it_worker_no_company_sees_no_tickets(self):
        self.make_ticket(self.worker)
        auth(self.client, self.it_no_company)
        res = self.client.get('/api/tickets/')
        self.assertEqual(res.data, [])

    def test_it_worker_sees_ticket_they_have_task_in(self):
        company2 = Company.objects.create(name='Lukoil')
        station2 = Station.objects.create(name='AZS-9', company=company2)
        worker2 = make_user('w_other', User.Role.WORKER, station=station2)
        ticket = self.make_ticket(worker2)
        Task.objects.create(ticket=ticket, assigned_to=self.it1)
        auth(self.client, self.it1)
        res = self.client.get('/api/tickets/')
        ids = [t['id'] for t in res.data]
        self.assertIn(ticket.id, ids)

    def test_admin_sees_non_resolved_tickets(self):
        t1 = self.make_ticket(self.worker)
        t2 = self.make_ticket(self.worker2)
        auth(self.client, self.admin)
        res = self.client.get('/api/tickets/')
        ids = [t['id'] for t in res.data]
        self.assertIn(t1.id, ids)
        self.assertIn(t2.id, ids)

    def test_nobody_sees_resolved_tickets(self):
        ticket = self.make_ticket(self.worker)
        ticket.status = Ticket.Status.RESOLVED
        ticket.rating = 5  # rated tickets are hidden from everyone including the worker
        ticket.save()
        for user in [self.worker, self.it1, self.manager, self.admin]:
            auth(self.client, user)
            res = self.client.get('/api/tickets/')
            ids = [t['id'] for t in res.data]
            self.assertNotIn(ticket.id, ids, msg=f'{user.role} should not see resolved ticket')

    def test_manager_sees_tickets_from_their_station(self):
        t1 = self.make_ticket(self.worker)
        t2 = self.make_ticket(self.worker2)
        auth(self.client, self.manager)
        res = self.client.get('/api/tickets/')
        ids = [t['id'] for t in res.data]
        self.assertIn(t1.id, ids)
        self.assertIn(t2.id, ids)

    def test_manager_cannot_see_tickets_from_other_station(self):
        other_station = Station.objects.create(name='AZS-99', company=self.company)
        other_worker = make_user('other_w2', User.Role.WORKER, station=other_station)
        ticket = self.make_ticket(other_worker)
        auth(self.client, self.manager)
        res = self.client.get('/api/tickets/')
        ids = [t['id'] for t in res.data]
        self.assertNotIn(ticket.id, ids)

    def test_it_worker_sees_in_progress_ticket_from_company(self):
        ticket = self.make_ticket(self.worker)
        ticket.status = Ticket.Status.IN_PROGRESS
        ticket.save()
        auth(self.client, self.it1)
        res = self.client.get('/api/tickets/')
        ids = [t['id'] for t in res.data]
        self.assertIn(ticket.id, ids)

    def test_worker_can_create_ticket(self):
        auth(self.client, self.worker)
        res = self.client.post('/api/tickets/', {'title': 'Screen broken', 'description': ''})
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Ticket.objects.filter(created_by=self.worker).count(), 1)

    def test_it_worker_cannot_create_ticket(self):
        auth(self.client, self.it1)
        res = self.client.post('/api/tickets/', {'title': 'Test', 'description': ''})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_manager_can_create_ticket_single_station(self):
        auth(self.client, self.manager)
        res = self.client.post('/api/tickets/', {'title': 'Supply issue', 'description': ''})
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        ticket = Ticket.objects.filter(created_by=self.manager).first()
        self.assertIsNotNone(ticket)
        self.assertEqual(ticket.station, self.station)

    def test_manager_must_choose_station_if_multiple(self):
        station2 = Station.objects.create(name='AZS-2', company=self.company)
        station2.deputies.add(self.manager)
        auth(self.client, self.manager)
        # without station_id → error
        res = self.client.post('/api/tickets/', {'title': 'Issue', 'description': ''})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        # with station_id → success
        res = self.client.post('/api/tickets/', {'title': 'Issue', 'description': '', 'station_id': station2.id})
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        ticket = Ticket.objects.filter(created_by=self.manager).first()
        self.assertEqual(ticket.station, station2)

    def test_manager_cannot_create_ticket_for_other_station(self):
        other_station = Station.objects.create(name='AZS-99', company=self.company)
        station2 = Station.objects.create(name='AZS-2', company=self.company)
        station2.deputies.add(self.manager)
        auth(self.client, self.manager)
        res = self.client.post('/api/tickets/', {'title': 'Issue', 'description': '', 'station_id': other_station.id})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)


# ── Ticket Detail ─────────────────────────────────────────────────────────────

class TicketDetailTests(BaseSetup):
    def test_worker_can_see_own_ticket(self):
        ticket = self.make_ticket(self.worker)
        auth(self.client, self.worker)
        res = self.client.get(f'/api/tickets/{ticket.id}/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_worker_cannot_see_other_ticket(self):
        ticket = self.make_ticket(self.worker2)
        auth(self.client, self.worker)
        res = self.client.get(f'/api/tickets/{ticket.id}/')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)


# ── Ticket Resolve ────────────────────────────────────────────────────────────

class TicketResolveTests(BaseSetup):
    def test_cannot_resolve_with_undone_tasks(self):
        ticket = self.make_ticket()
        self.make_task(ticket, self.it1)  # task still open
        auth(self.client, self.it1)
        from unittest.mock import patch
        with patch('api.views.push_to_zammad'):
            res = self.client.post(f'/api/tickets/{ticket.id}/resolve/')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        ticket.refresh_from_db()
        self.assertNotEqual(ticket.status, Ticket.Status.RESOLVED)

    def test_can_resolve_when_all_tasks_done(self):
        ticket = self.make_ticket()
        task = self.make_task(ticket, self.it1)
        task.status = Task.Status.DONE
        task.save()
        auth(self.client, self.it1)
        from unittest.mock import patch
        with patch('api.views.push_to_zammad'):
            res = self.client.post(f'/api/tickets/{ticket.id}/resolve/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.RESOLVED)

    def test_worker_cannot_resolve_ticket(self):
        ticket = self.make_ticket()
        auth(self.client, self.worker)
        res = self.client.post(f'/api/tickets/{ticket.id}/resolve/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_it_worker_without_task_cannot_resolve(self):
        ticket = self.make_ticket()
        auth(self.client, self.it2)
        from unittest.mock import patch
        with patch('api.views.push_to_zammad'):
            res = self.client.post(f'/api/tickets/{ticket.id}/resolve/')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)


# ── Task Create / Update ──────────────────────────────────────────────────────

class TaskTests(BaseSetup):
    def test_it_worker_can_take_ticket(self):
        ticket = self.make_ticket()
        auth(self.client, self.it1)
        res = self.client.post(f'/api/tickets/{ticket.id}/tasks/', {
            'assigned_to': self.it1.id,
            'status': 'open',
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Task.objects.filter(ticket=ticket, assigned_to=self.it1).exists())

    def test_it_worker_cannot_delegate_to_wrong_company(self):
        company2 = Company.objects.create(name='BP')
        it_other = make_user('it_bp', User.Role.IT_WORKER, companies=[company2])
        ticket = self.make_ticket()
        auth(self.client, self.it1)
        res = self.client.post(f'/api/tickets/{ticket.id}/tasks/', {
            'assigned_to': it_other.id,
            'status': 'open',
        })
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_worker_cannot_create_task(self):
        ticket = self.make_ticket()
        auth(self.client, self.worker)
        res = self.client.post(f'/api/tickets/{ticket.id}/tasks/', {
            'assigned_to': self.it1.id,
        })
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_it_worker_can_update_own_task(self):
        ticket = self.make_ticket()
        task = self.make_task(ticket, self.it1)
        auth(self.client, self.it1)
        res = self.client.patch(f'/api/tasks/{task.id}/', {'status': 'in_progress'})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.IN_PROGRESS)
        self.assertIsNotNone(task.started_at)

    def test_it_worker_cannot_update_others_task(self):
        ticket = self.make_ticket()
        task = self.make_task(ticket, self.it1)
        auth(self.client, self.it2)
        res = self.client.patch(f'/api/tasks/{task.id}/', {'status': 'in_progress'})
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_task_done_sets_finished_at(self):
        ticket = self.make_ticket()
        task = self.make_task(ticket, self.it1)
        task.status = Task.Status.IN_PROGRESS
        task.save()
        auth(self.client, self.it1)
        res = self.client.patch(f'/api/tasks/{task.id}/', {'status': 'done'})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        task.refresh_from_db()
        self.assertIsNotNone(task.finished_at)


# ── Comments ──────────────────────────────────────────────────────────────────

class CommentTests(BaseSetup):
    def test_worker_can_post_public_comment(self):
        ticket = self.make_ticket()
        auth(self.client, self.worker)
        res = self.client.post(f'/api/tickets/{ticket.id}/comments/', {'text': 'Hello'})
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_worker_cannot_post_internal_comment(self):
        ticket = self.make_ticket()
        auth(self.client, self.worker)
        res = self.client.post(f'/api/tickets/{ticket.id}/comments/', {
            'text': 'secret', 'is_internal': True
        })
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_it_worker_can_post_internal_comment(self):
        ticket = self.make_ticket()
        self.make_task(ticket, self.it1)
        auth(self.client, self.it1)
        res = self.client.post(f'/api/tickets/{ticket.id}/comments/', {
            'text': 'internal note', 'is_internal': True
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_worker_cannot_see_internal_comments(self):
        ticket = self.make_ticket(self.worker)
        Comment.objects.create(ticket=ticket, author=self.it1, text='private', is_internal=True)
        Comment.objects.create(ticket=ticket, author=self.it1, text='public', is_internal=False)
        auth(self.client, self.worker)
        res = self.client.get(f'/api/tickets/{ticket.id}/')
        texts = [c['text'] for c in res.data['comments']]
        self.assertNotIn('private', texts)
        self.assertIn('public', texts)

    def test_manager_can_post_public_comment_on_own_station_ticket(self):
        ticket = self.make_ticket(self.worker)
        auth(self.client, self.manager)
        res = self.client.post(f'/api/tickets/{ticket.id}/comments/', {'text': 'hello'})
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_manager_cannot_post_internal_comment(self):
        ticket = self.make_ticket(self.worker)
        auth(self.client, self.manager)
        res = self.client.post(f'/api/tickets/{ticket.id}/comments/', {
            'text': 'secret', 'is_internal': True
        })
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_manager_cannot_post_comment_on_other_station_ticket(self):
        other_station = Station.objects.create(name='AZS-99', company=self.company)
        other_worker = make_user('other_w_mgr', User.Role.WORKER, station=other_station)
        ticket = self.make_ticket(other_worker)
        auth(self.client, self.manager)
        res = self.client.post(f'/api/tickets/{ticket.id}/comments/', {'text': 'hello'})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_manager_cannot_post_comment_on_resolved_ticket(self):
        ticket = self.make_ticket(self.worker)
        ticket.status = Ticket.Status.RESOLVED
        ticket.save()
        auth(self.client, self.manager)
        res = self.client.post(f'/api/tickets/{ticket.id}/comments/', {'text': 'hello'})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_manager_cannot_see_internal_comments(self):
        ticket = self.make_ticket(self.worker)
        Comment.objects.create(ticket=ticket, author=self.it1, text='secret', is_internal=True)
        Comment.objects.create(ticket=ticket, author=self.it1, text='public', is_internal=False)
        auth(self.client, self.manager)
        res = self.client.get(f'/api/tickets/{ticket.id}/')
        texts = [c['text'] for c in res.data['comments']]
        self.assertNotIn('secret', texts)
        self.assertIn('public', texts)

    def test_it_worker_sees_all_comments(self):
        ticket = self.make_ticket(self.worker)
        self.make_task(ticket, self.it1)
        Comment.objects.create(ticket=ticket, author=self.it1, text='private', is_internal=True)
        Comment.objects.create(ticket=ticket, author=self.it1, text='public', is_internal=False)
        auth(self.client, self.it1)
        res = self.client.get(f'/api/tickets/{ticket.id}/')
        texts = [c['text'] for c in res.data['comments']]
        self.assertIn('private', texts)
        self.assertIn('public', texts)


# ── IT Worker List ────────────────────────────────────────────────────────────

class ITWorkerListTests(BaseSetup):
    def test_returns_workers_for_ticket_company(self):
        ticket = self.make_ticket()
        auth(self.client, self.it1)
        res = self.client.get(f'/api/it-workers/?ticket_id={ticket.id}')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        ids = [w['id'] for w in res.data]
        self.assertIn(self.it2.id, ids)
        self.assertNotIn(self.it_no_company.id, ids)
        self.assertNotIn(self.it1.id, ids)  # excludes self

    def test_excludes_workers_from_other_company(self):
        company2 = Company.objects.create(name='BP')
        it_bp = make_user('it_bp', User.Role.IT_WORKER, companies=[company2])
        ticket = self.make_ticket()
        auth(self.client, self.it1)
        res = self.client.get(f'/api/it-workers/?ticket_id={ticket.id}')
        ids = [w['id'] for w in res.data]
        self.assertNotIn(it_bp.id, ids)

    def test_worker_cannot_access_it_workers_list(self):
        auth(self.client, self.worker)
        res = self.client.get('/api/it-workers/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)


# ── Station Workers ───────────────────────────────────────────────────────────

class StationWorkerTests(BaseSetup):
    def test_manager_can_list_station_workers(self):
        auth(self.client, self.manager)
        res = self.client.get('/api/station/workers/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        ids = [w['id'] for w in res.data]
        self.assertIn(self.worker.id, ids)

    def test_manager_can_add_worker(self):
        auth(self.client, self.manager)
        res = self.client.post('/api/station/workers/', {
            'username': 'new_worker',
            'password': 'pass1234',
            'first_name': 'New',
            'last_name': 'Worker',
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(username='new_worker').exists())

    def test_manager_can_deactivate_worker(self):
        auth(self.client, self.manager)
        res = self.client.delete(f'/api/station/workers/{self.worker.id}/')
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        self.worker.refresh_from_db()
        self.assertFalse(self.worker.is_active)

    def test_manager_cannot_deactivate_worker_from_other_station(self):
        other_station = Station.objects.create(name='AZS-99', company=self.company)
        other_worker = make_user('other_w', User.Role.WORKER, station=other_station)
        auth(self.client, self.manager)
        res = self.client.delete(f'/api/station/workers/{other_worker.id}/')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_it_worker_cannot_manage_station(self):
        auth(self.client, self.it1)
        res = self.client.get('/api/station/workers/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_duplicate_username_rejected(self):
        auth(self.client, self.manager)
        res = self.client.post('/api/station/workers/', {
            'username': 'worker1',
            'password': 'pass1234',
        })
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)


# ── Supply Worker ─────────────────────────────────────────────────────────────

class SupplyWorkerTests(BaseSetup):
    def setUp(self):
        super().setUp()
        self.supply = make_user('supply1', User.Role.SUPPLY_WORKER, companies=[self.company])

    def test_supply_worker_sees_only_delegated_tickets(self):
        t_delegated = self.make_ticket(self.worker)
        t_other = self.make_ticket(self.worker2)
        Task.objects.create(ticket=t_delegated, assigned_to=self.supply)
        auth(self.client, self.supply)
        res = self.client.get('/api/tickets/')
        ids = [t['id'] for t in res.data]
        self.assertIn(t_delegated.id, ids)
        self.assertNotIn(t_other.id, ids)

    def test_supply_worker_sees_no_tickets_without_task(self):
        self.make_ticket(self.worker)
        auth(self.client, self.supply)
        res = self.client.get('/api/tickets/')
        self.assertEqual(res.data, [])

    def test_supply_worker_cannot_see_resolved_ticket(self):
        ticket = self.make_ticket(self.worker)
        Task.objects.create(ticket=ticket, assigned_to=self.supply)
        ticket.status = Ticket.Status.RESOLVED
        ticket.save()
        auth(self.client, self.supply)
        res = self.client.get('/api/tickets/')
        self.assertEqual(res.data, [])

    def test_supply_worker_can_update_task_status(self):
        ticket = self.make_ticket(self.worker)
        task = Task.objects.create(ticket=ticket, assigned_to=self.supply)
        auth(self.client, self.supply)
        res = self.client.patch(f'/api/tasks/{task.id}/', {'status': 'in_progress'})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.IN_PROGRESS)

    def test_supply_worker_cannot_update_others_task(self):
        ticket = self.make_ticket(self.worker)
        task = self.make_task(ticket, self.it1)
        auth(self.client, self.supply)
        res = self.client.patch(f'/api/tasks/{task.id}/', {'status': 'in_progress'})
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_supply_worker_cannot_see_internal_comments(self):
        ticket = self.make_ticket(self.worker)
        Task.objects.create(ticket=ticket, assigned_to=self.supply)
        Comment.objects.create(ticket=ticket, author=self.it1, text='secret', is_internal=True)
        Comment.objects.create(ticket=ticket, author=self.it1, text='public', is_internal=False)
        auth(self.client, self.supply)
        res = self.client.get(f'/api/tickets/{ticket.id}/')
        texts = [c['text'] for c in res.data['comments']]
        self.assertNotIn('secret', texts)
        self.assertIn('public', texts)

    def test_supply_worker_cannot_post_internal_comment(self):
        ticket = self.make_ticket(self.worker)
        Task.objects.create(ticket=ticket, assigned_to=self.supply)
        auth(self.client, self.supply)
        res = self.client.post(f'/api/tickets/{ticket.id}/comments/', {
            'text': 'internal', 'is_internal': True
        })
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_supply_worker_appears_in_delegation_list(self):
        ticket = self.make_ticket(self.worker)
        auth(self.client, self.it1)
        res = self.client.get(f'/api/it-workers/?ticket_id={ticket.id}')
        ids = [w['id'] for w in res.data]
        self.assertIn(self.supply.id, ids)

    def test_supply_worker_cannot_resolve_ticket(self):
        ticket = self.make_ticket(self.worker)
        task = Task.objects.create(ticket=ticket, assigned_to=self.supply)
        task.status = Task.Status.DONE
        task.save()
        auth(self.client, self.supply)
        res = self.client.post(f'/api/tickets/{ticket.id}/resolve/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_supply_worker_cannot_create_ticket(self):
        auth(self.client, self.supply)
        res = self.client.post('/api/tickets/', {'title': 'Test', 'description': ''})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)


# ── Deputy ────────────────────────────────────────────────────────────────────

class DeputyTests(BaseSetup):
    def setUp(self):
        super().setUp()
        self.deputy = make_user('deputy1', User.Role.DEPUTY)
        self.station.deputies.add(self.deputy)

    def test_deputy_sees_station_tickets(self):
        ticket = self.make_ticket(self.worker)
        auth(self.client, self.deputy)
        res = self.client.get('/api/tickets/')
        self.assertIn(ticket.id, [t['id'] for t in res.data])

    def test_deputy_cannot_see_other_station_tickets(self):
        other_station = Station.objects.create(name='AZS-99', company=self.company)
        other_worker = make_user('other_w3', User.Role.WORKER, station=other_station)
        ticket = self.make_ticket(other_worker)
        auth(self.client, self.deputy)
        res = self.client.get('/api/tickets/')
        self.assertNotIn(ticket.id, [t['id'] for t in res.data])

    def test_deputy_can_create_ticket(self):
        auth(self.client, self.deputy)
        res = self.client.post('/api/tickets/', {'title': 'Deputy ticket', 'description': ''})
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_deputy_cannot_post_comment(self):
        ticket = self.make_ticket(self.worker)
        auth(self.client, self.deputy)
        res = self.client.post(f'/api/tickets/{ticket.id}/comments/', {'text': 'hello'})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_deputy_cannot_see_internal_comments(self):
        ticket = self.make_ticket(self.worker)
        Comment.objects.create(ticket=ticket, author=self.it1, text='secret', is_internal=True)
        auth(self.client, self.deputy)
        res = self.client.get(f'/api/tickets/{ticket.id}/')
        texts = [c['text'] for c in res.data['comments']]
        self.assertNotIn('secret', texts)

    def test_deputy_can_manage_station_workers(self):
        auth(self.client, self.deputy)
        res = self.client.get('/api/station/workers/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_deputy_cannot_manage_deputies(self):
        auth(self.client, self.deputy)
        res = self.client.get('/api/station/deputies/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    # Station manager deputy management
    def test_manager_can_list_deputies(self):
        auth(self.client, self.manager)
        res = self.client.get('/api/station/deputies/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        ids = [d['id'] for d in res.data]
        self.assertIn(self.deputy.id, ids)

    def test_manager_can_promote_worker_to_deputy(self):
        auth(self.client, self.manager)
        res = self.client.post('/api/station/deputies/', {'worker_id': self.worker.id})
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.worker.refresh_from_db()
        self.assertEqual(self.worker.role, User.Role.DEPUTY)
        self.assertIsNone(self.worker.station)
        self.assertIn(self.worker, self.station.deputies.all())

    def test_manager_can_create_new_deputy(self):
        auth(self.client, self.manager)
        res = self.client.post('/api/station/deputies/', {'username': 'new_dep', 'password': 'pass1234'})
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        deputy = User.objects.get(username='new_dep')
        self.assertEqual(deputy.role, User.Role.DEPUTY)
        self.assertIn(deputy, self.station.deputies.all())

    def test_manager_cannot_promote_worker_from_other_station(self):
        other_station = Station.objects.create(name='AZS-99', company=self.company)
        other_worker = make_user('other_w4', User.Role.WORKER, station=other_station)
        auth(self.client, self.manager)
        res = self.client.post('/api/station/deputies/', {'worker_id': other_worker.id})
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_manager_can_remove_deputy(self):
        auth(self.client, self.manager)
        res = self.client.delete(f'/api/station/deputies/{self.deputy.id}/')
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        self.deputy.refresh_from_db()
        self.assertFalse(self.deputy.is_active)


# ── IT Manager ────────────────────────────────────────────────────────────────

class ITManagerTests(BaseSetup):
    def setUp(self):
        super().setUp()
        self.it_manager = make_user('itman', User.Role.IT_MANAGER, companies=[self.company])

    # Works like IT worker
    def test_it_manager_sees_tickets_from_company(self):
        ticket = self.make_ticket(self.worker)
        auth(self.client, self.it_manager)
        res = self.client.get('/api/tickets/')
        self.assertIn(ticket.id, [t['id'] for t in res.data])

    def test_it_manager_can_take_ticket(self):
        ticket = self.make_ticket()
        auth(self.client, self.it_manager)
        res = self.client.post(f'/api/tickets/{ticket.id}/tasks/', {'assigned_to': self.it_manager.id, 'status': 'open'})
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_it_manager_appears_in_delegation_list(self):
        ticket = self.make_ticket()
        auth(self.client, self.it1)
        res = self.client.get(f'/api/it-workers/?ticket_id={ticket.id}')
        ids = [w['id'] for w in res.data]
        self.assertIn(self.it_manager.id, ids)

    # Manage IT workers
    def test_it_manager_can_list_it_workers(self):
        auth(self.client, self.it_manager)
        res = self.client.get('/api/manage/it-workers/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        ids = [w['id'] for w in res.data]
        self.assertIn(self.it1.id, ids)

    def test_it_manager_can_add_it_worker(self):
        auth(self.client, self.it_manager)
        res = self.client.post('/api/manage/it-workers/', {'username': 'new_it', 'password': 'pass1234', 'first_name': 'New', 'last_name': 'IT'})
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        worker = User.objects.get(username='new_it')
        self.assertEqual(worker.role, User.Role.IT_WORKER)
        self.assertIn(self.company, worker.companies.all())

    def test_it_manager_can_deactivate_it_worker(self):
        auth(self.client, self.it_manager)
        res = self.client.delete(f'/api/manage/it-workers/{self.it1.id}/')
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        self.it1.refresh_from_db()
        self.assertFalse(self.it1.is_active)

    def test_it_manager_cannot_manage_it_worker_from_other_company(self):
        company2 = Company.objects.create(name='BP')
        other_it = make_user('other_it', User.Role.IT_WORKER, companies=[company2])
        auth(self.client, self.it_manager)
        res = self.client.delete(f'/api/manage/it-workers/{other_it.id}/')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    # Manage supply workers
    def test_it_manager_can_add_supply_worker(self):
        auth(self.client, self.it_manager)
        res = self.client.post('/api/manage/supply-workers/', {'username': 'new_supply', 'password': 'pass1234'})
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        worker = User.objects.get(username='new_supply')
        self.assertEqual(worker.role, User.Role.SUPPLY_WORKER)
        self.assertIn(self.company, worker.companies.all())

    def test_it_manager_can_deactivate_supply_worker(self):
        supply = make_user('supply_x', User.Role.SUPPLY_WORKER, companies=[self.company])
        auth(self.client, self.it_manager)
        res = self.client.delete(f'/api/manage/supply-workers/{supply.id}/')
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        supply.refresh_from_db()
        self.assertFalse(supply.is_active)

    # Manage station managers
    def test_it_manager_can_add_station_manager(self):
        auth(self.client, self.it_manager)
        res = self.client.post('/api/manage/station-managers/', {
            'username': 'new_mgr', 'password': 'pass1234', 'station_id': self.station.id
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        mgr = User.objects.get(username='new_mgr')
        self.assertEqual(mgr.role, User.Role.STATION_MANAGER)

    def test_it_manager_cannot_add_station_manager_to_other_company_station(self):
        company2 = Company.objects.create(name='BP')
        other_station = Station.objects.create(name='AZS-BP', company=company2)
        auth(self.client, self.it_manager)
        res = self.client.post('/api/manage/station-managers/', {
            'username': 'new_mgr2', 'password': 'pass1234', 'station_id': other_station.id
        })
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_it_manager_can_deactivate_station_manager(self):
        auth(self.client, self.it_manager)
        res = self.client.delete(f'/api/manage/station-managers/{self.manager.id}/')
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        self.manager.refresh_from_db()
        self.assertFalse(self.manager.is_active)

    def test_it_worker_cannot_access_management_endpoints(self):
        auth(self.client, self.it1)
        res = self.client.get('/api/manage/it-workers/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)


# ── Change Password ───────────────────────────────────────────────────────────

class ChangePasswordTests(BaseSetup):
    def test_correct_password_change(self):
        auth(self.client, self.worker)
        res = self.client.post('/api/auth/change-password/', {
            'old_password': 'pass1234',
            'new_password': 'newpass99',
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.worker.refresh_from_db()
        self.assertTrue(self.worker.check_password('newpass99'))

    def test_wrong_old_password_rejected(self):
        auth(self.client, self.worker)
        res = self.client.post('/api/auth/change-password/', {
            'old_password': 'wrongpass',
            'new_password': 'newpass99',
        })
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_short_new_password_rejected(self):
        auth(self.client, self.worker)
        res = self.client.post('/api/auth/change-password/', {
            'old_password': 'pass1234',
            'new_password': '123',
        })
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
