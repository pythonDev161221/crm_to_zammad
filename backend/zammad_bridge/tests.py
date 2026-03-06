from django.test import TestCase
from unittest.mock import patch, MagicMock, call

from users.models import User, Station, Company
from tasks.models import Ticket, Task, Comment
from zammad_bridge.client import push_to_zammad
from zammad_bridge.agent_sync import sync_agent_created, sync_agent_companies


def make_user(username, role, station=None, companies=None):
    u = User.objects.create_user(username=username, password='pass', role=role, station=station)
    if companies:
        u.companies.set(companies)
    return u


class PushToZammadTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Shell')
        self.station = Station.objects.create(name='AZS-1', company=self.company)
        self.worker = make_user('worker1', User.Role.WORKER, station=self.station)
        self.it1 = make_user('it1', User.Role.IT_WORKER, companies=[self.company])
        self.it2 = make_user('it2', User.Role.IT_WORKER, companies=[self.company])

    def _make_resolved_ticket(self):
        ticket = Ticket.objects.create(
            created_by=self.worker,
            title='Printer broken',
            description='Does not print',
            status=Ticket.Status.RESOLVED,
        )
        task1 = Task.objects.create(ticket=ticket, assigned_to=self.it1, status=Task.Status.DONE)
        task2 = Task.objects.create(ticket=ticket, assigned_to=self.it2, status=Task.Status.DONE)
        Comment.objects.create(ticket=ticket, author=self.worker, text='Please fix', is_internal=False)
        Comment.objects.create(ticket=ticket, author=self.it1, text='On it', is_internal=True)
        return ticket

    @patch('zammad_bridge.client.requests.get')
    @patch('zammad_bridge.client.requests.post')
    def test_push_creates_zammad_ticket(self, mock_post, mock_get):
        mock_get.return_value = MagicMock(status_code=200, json=lambda: [])
        mock_post.return_value = MagicMock(status_code=201, json=lambda: {'id': 42})

        ticket = self._make_resolved_ticket()
        push_to_zammad(ticket)

        # Find the ticket creation call (not /groups, /organizations, or /ticket_articles)
        ticket_call = next(
            c for c in mock_post.call_args_list
            if c[0][0].endswith('/tickets')
        )
        payload = ticket_call[1]['json']
        self.assertEqual(payload['title'], 'Printer broken')
        self.assertEqual(payload['group'], 'Shell')
        self.assertEqual(payload['organization'], 'AZS-1')
        self.assertEqual(payload['customer'], 'worker1')

    @patch('zammad_bridge.client.requests.get')
    @patch('zammad_bridge.client.requests.post')
    def test_push_creates_articles_for_tasks_and_comments(self, mock_post, mock_get):
        mock_get.return_value = MagicMock(status_code=200, json=lambda: [])
        mock_post.return_value = MagicMock(status_code=201, json=lambda: {'id': 42})

        ticket = self._make_resolved_ticket()
        push_to_zammad(ticket)

        article_calls = [
            c for c in mock_post.call_args_list
            if '/ticket_articles' in c[0][0]
        ]
        # 2 tasks + 2 comments = 4 articles
        self.assertEqual(len(article_calls), 4)

    @patch('zammad_bridge.client.requests.get')
    @patch('zammad_bridge.client.requests.post')
    def test_push_sets_zammad_synced_true(self, mock_post, mock_get):
        mock_get.return_value = MagicMock(status_code=200, json=lambda: [])
        mock_post.return_value = MagicMock(status_code=201, json=lambda: {'id': 42})

        ticket = self._make_resolved_ticket()
        push_to_zammad(ticket)

        ticket.refresh_from_db()
        self.assertTrue(ticket.zammad_synced)

    @patch('zammad_bridge.client.requests.get')
    @patch('zammad_bridge.client.requests.post')
    def test_internal_comments_are_internal_articles(self, mock_post, mock_get):
        mock_get.return_value = MagicMock(status_code=200, json=lambda: [])
        mock_post.return_value = MagicMock(status_code=201, json=lambda: {'id': 42})

        ticket = self._make_resolved_ticket()
        push_to_zammad(ticket)

        article_calls = [
            c[1]['json'] for c in mock_post.call_args_list
            if '/ticket_articles' in c[0][0]
        ]
        internal_articles = [a for a in article_calls if a.get('internal') is True]
        public_articles = [a for a in article_calls if a.get('internal') is False]
        # 2 tasks (internal) + 1 internal comment = 3 internal, 1 public
        self.assertEqual(len(internal_articles), 3)
        self.assertEqual(len(public_articles), 1)

    @patch('zammad_bridge.client.requests.get')
    @patch('zammad_bridge.client.requests.post')
    def test_push_failure_does_not_set_synced(self, mock_post, mock_get):
        mock_get.return_value = MagicMock(status_code=200, json=lambda: [])
        mock_post.side_effect = Exception('Connection refused')

        ticket = self._make_resolved_ticket()
        with self.assertRaises(Exception):
            push_to_zammad(ticket)

        ticket.refresh_from_db()
        self.assertFalse(ticket.zammad_synced)

    @patch('zammad_bridge.client.requests.get')
    @patch('zammad_bridge.client.requests.post')
    def test_auto_creates_group_if_missing(self, mock_post, mock_get):
        mock_get.return_value = MagicMock(status_code=200, json=lambda: [])
        mock_post.return_value = MagicMock(status_code=201, json=lambda: {'id': 1})

        ticket = self._make_resolved_ticket()
        push_to_zammad(ticket)

        group_create_calls = [
            c for c in mock_post.call_args_list
            if '/groups' in c[0][0]
        ]
        self.assertTrue(len(group_create_calls) > 0)

    @patch('zammad_bridge.client.requests.get')
    @patch('zammad_bridge.client.requests.post')
    def test_skips_group_creation_if_exists(self, mock_post, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: [{'id': 5, 'name': 'Shell'}]
        )
        mock_post.return_value = MagicMock(status_code=201, json=lambda: {'id': 42})

        ticket = self._make_resolved_ticket()
        push_to_zammad(ticket)

        group_create_calls = [
            c for c in mock_post.call_args_list
            if '/groups' in c[0][0]
        ]
        self.assertEqual(len(group_create_calls), 0)


class AgentSyncTests(TestCase):
    def setUp(self):
        self.company1 = Company.objects.create(name='Shell')
        self.company2 = Company.objects.create(name='BP')
        self.it = make_user('it_worker', User.Role.IT_WORKER, companies=[self.company1])

    @patch('zammad_bridge.agent_sync.ZammadClient')
    def test_sync_agent_created(self, MockClient):
        mock_client = MockClient.return_value
        mock_client.get_or_create_agent.return_value = 99

        sync_agent_created(self.it)

        mock_client.get_or_create_agent.assert_called_once_with(self.it)

    @patch('zammad_bridge.agent_sync.ZammadClient')
    def test_sync_agent_companies_sets_correct_groups(self, MockClient):
        mock_client = MockClient.return_value
        mock_client.get_or_create_agent.return_value = 99
        mock_client.get_or_create_group.side_effect = lambda name: {'Shell': 1, 'BP': 2}[name]

        self.it.companies.set([self.company1, self.company2])
        sync_agent_companies(self.it)

        mock_client.set_agent_groups.assert_called_once()
        group_ids = set(mock_client.set_agent_groups.call_args[0][1])
        self.assertEqual(group_ids, {1, 2})

    @patch('zammad_bridge.agent_sync.ZammadClient')
    def test_sync_agent_no_companies_sets_empty_groups(self, MockClient):
        mock_client = MockClient.return_value
        mock_client.get_or_create_agent.return_value = 99

        self.it.companies.clear()
        sync_agent_companies(self.it)

        mock_client.set_agent_groups.assert_called_once_with(99, [])

    @patch('zammad_bridge.agent_sync.ZammadClient')
    def test_sync_raises_on_failure(self, MockClient):
        mock_client = MockClient.return_value
        mock_client.get_or_create_agent.side_effect = Exception('Zammad down')

        with self.assertRaises(Exception):
            sync_agent_created(self.it)
