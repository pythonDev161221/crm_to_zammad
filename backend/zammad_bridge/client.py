import base64
import logging
import mimetypes
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class ZammadClient:
    def __init__(self):
        self.base_url = settings.ZAMMAD_URL.rstrip('/')
        self.headers = {
            'Authorization': f'Token token={settings.ZAMMAD_TOKEN}',
            'Content-Type': 'application/json',
        }

    def _url(self, endpoint):
        return f'{self.base_url}/api/v1{endpoint}'

    def get(self, endpoint, params=None):
        response = requests.get(self._url(endpoint), params=params, headers=self.headers, timeout=10)
        response.raise_for_status()
        return response.json()

    def post(self, endpoint, data):
        response = requests.post(self._url(endpoint), json=data, headers=self.headers, timeout=10)
        response.raise_for_status()
        return response.json()

    def put(self, endpoint, data):
        response = requests.put(self._url(endpoint), json=data, headers=self.headers, timeout=10)
        response.raise_for_status()
        return response.json()

    # ── Groups ────────────────────────────────────────────────────────────────

    def get_or_create_group(self, name):
        """Returns (group_id, full_group_name)."""
        groups = self.get('/groups')
        users_group_id = next((g['id'] for g in groups if g['name'] == 'Users'), None)
        for g in groups:
            if g.get('name_last') == name or g.get('name') == name:
                return g['id'], g['name']
        payload = {'name': name, 'active': True}
        if users_group_id:
            payload['parent_id'] = users_group_id
        result = self.post('/groups', payload)
        group_id = result['id']
        full_name = result.get('name', name)
        try:
            me = self.get('/users/me')
            current_groups = me.get('group_ids', {})
            current_groups[str(group_id)] = ['full']
            self.put(f'/users/{me["id"]}', {'group_ids': current_groups})
        except Exception as e:
            logger.warning(f'Failed to assign new Zammad group {name!r} to API user: {e}')
        return group_id, full_name

    # ── Organizations ─────────────────────────────────────────────────────────

    def get_or_create_organization(self, name):
        results = self.get('/organizations/search', params={'query': name, 'limit': 10})
        for o in results:
            if o['name'] == name:
                return o['id']
        result = self.post('/organizations', {'name': name, 'active': True})
        return result['id']

    # ── Agents ────────────────────────────────────────────────────────────────

    def get_or_create_agent(self, user):
        results = self.get('/users/search', params={'query': user.username, 'limit': 10})
        for u in results:
            if u.get('login') == user.username:
                return u['id']
        try:
            result = self.post('/users', {
                'firstname': user.first_name or user.username,
                'lastname': user.last_name or '',
                'login': user.username,
                'email': user.email or f'{user.username}@internal.local',
                'roles': ['Agent'],
                'active': True,
            })
            return result['id']
        except Exception as e:
            if '422' in str(e):
                all_users = self.get('/users')
                for u in all_users:
                    if u.get('login', '').lower() == user.username.lower():
                        self.put(f'/users/{u["id"]}', {'roles': ['Agent']})
                        return u['id']
            raise

    def set_agent_groups(self, agent_id, group_ids):
        """Replace agent's group membership with the given list of group IDs."""
        group_ids_payload = {str(gid): ['full'] for gid in group_ids}
        self.put(f'/users/{agent_id}', {'group_ids': group_ids_payload})

    def get_or_create_station_customer(self, station, organization_id=None):
        """Create/find a Zammad customer representing the station (not individual worker)."""
        login = station.name.lower().replace(' ', '_')
        results = self.get('/users/search', params={'query': login, 'limit': 10})
        for u in results:
            if u.get('login', '').lower() == login:
                return u['login']
        payload = {
            'firstname': station.name,
            'lastname': '',
            'login': login,
            'email': f'{login}@internal.local',
            'roles': ['Customer'],
            'active': True,
        }
        if organization_id:
            payload['organization_id'] = organization_id
        try:
            result = self.post('/users', payload)
            return result.get('login', login)
        except Exception:
            all_users = self.get('/users')
            for u in all_users:
                if u.get('login', '').lower() == login:
                    return u['login']
            raise


def _photo_attachments(photos):
    attachments = []
    for photo in photos:
        try:
            with photo.image.open('rb') as f:
                data = base64.b64encode(f.read()).decode('utf-8')
            mime = mimetypes.guess_type(photo.image.name)[0] or 'image/jpeg'
            filename = photo.image.name.split('/')[-1]
            attachments.append({'filename': filename, 'data': data, 'mime-type': mime})
        except Exception as e:
            logger.warning(f'Failed to encode photo attachment {photo.pk}: {e}')
    return attachments


def push_to_zammad(ticket):
    client = ZammadClient()

    station = ticket.station
    company = station.company if station else None

    group_id, group_full_name = client.get_or_create_group(company.name if company else 'Users')

    org_id = None
    if company:
        org_id = client.get_or_create_organization(company.name)

    if station:
        customer_login = client.get_or_create_station_customer(station, organization_id=org_id)
    else:
        # No station — fall back to worker as customer
        worker_login = ticket.created_by.username.lower()
        results = client.get('/users/search', params={'query': worker_login, 'limit': 10})
        existing = next((u['login'] for u in results if u.get('login', '').lower() == worker_login), None)
        if existing:
            customer_login = existing
        else:
            result = client.post('/users', {
                'firstname': ticket.created_by.first_name or ticket.created_by.username,
                'lastname': ticket.created_by.last_name or '',
                'login': worker_login,
                'email': ticket.created_by.email or f'{worker_login}@internal.local',
                'roles': ['Customer'],
                'active': True,
            })
            customer_login = result.get('login', worker_login)

    owner_login = None
    if ticket.resolved_by:
        agent_id = client.get_or_create_agent(ticket.resolved_by)
        client.set_agent_groups(agent_id, [group_id])
        owner_login = ticket.resolved_by.username.lower()

    worker = ticket.created_by
    worker_name = worker.get_full_name() or worker.username
    body = f'Worker: {worker_name}\n'
    if worker.phone:
        body += f'Phone: {worker.phone}\n'
    body += f'\n{ticket.description or ticket.title}'
    ticket_attachments = _photo_attachments(ticket.photos.all())

    article_payload = {
        'subject': ticket.title,
        'body': body,
        'type': 'note',
        'internal': False,
    }
    if ticket_attachments:
        article_payload['attachments'] = ticket_attachments

    ticket_payload = {
        'title': ticket.title,
        'group': group_full_name,
        'customer': customer_login,
        'state': 'closed',
        'article': article_payload,
    }
    if owner_login:
        ticket_payload['owner'] = owner_login

    zammad_ticket = client.post('/tickets', ticket_payload)

    zammad_ticket_id = zammad_ticket['id']

    for task in ticket.tasks.select_related('assigned_to').all():
        duration = None
        if task.started_at and task.finished_at:
            duration = str(task.finished_at - task.started_at)

        body = f'IT Worker: {task.assigned_to.get_full_name() or task.assigned_to.username}\n'
        body += f'Status: {task.status}\n'
        if duration:
            body += f'Duration: {duration}\n'
        if task.notes:
            body += f'\nNotes:\n{task.notes}'

        client.post('/ticket_articles', {
            'ticket_id': zammad_ticket_id,
            'subject': f'Task by {task.assigned_to.username}',
            'body': body,
            'type': 'note',
            'internal': True,
        })

    for comment in ticket.comments.select_related('author').prefetch_related('photos').all():
        author_name = comment.author.get_full_name() or comment.author.username
        comment_payload = {
            'ticket_id': zammad_ticket_id,
            'subject': f'Comment by {author_name}',
            'body': comment.text or '(photo)',
            'type': 'note',
            'internal': comment.is_internal,
        }
        comment_attachments = _photo_attachments(comment.photos.all())
        if comment_attachments:
            comment_payload['attachments'] = comment_attachments
        client.post('/ticket_articles', comment_payload)

    ticket.zammad_synced = True
    ticket.save(update_fields=['zammad_synced'])
