import requests
from django.conf import settings


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
        groups = self.get('/groups')
        for g in groups:
            if g['name'] == name:
                return g['id']
        result = self.post('/groups', {'name': name, 'active': True})
        return result['id']

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
        result = self.post('/users', {
            'firstname': user.first_name or user.username,
            'lastname': user.last_name or '',
            'login': user.username,
            'email': user.email or f'{user.username}@internal.local',
            'roles': ['Agent'],
            'active': True,
        })
        return result['id']

    def set_agent_groups(self, agent_id, group_ids):
        """Replace agent's group membership with the given list of group IDs."""
        group_ids_payload = {str(gid): ['full'] for gid in group_ids}
        self.put(f'/users/{agent_id}', {'group_ids': group_ids_payload})


def push_to_zammad(task):
    client = ZammadClient()

    station = task.created_by.station
    company = station.company if station else None

    group_name = company.name if company else 'Users'
    client.get_or_create_group(group_name)

    if station:
        client.get_or_create_organization(station.name)

    zammad_ticket = client.post('/tickets', {
        'title': task.title,
        'group': group_name,
        'organization': station.name if station else None,
        'customer': task.created_by.username,
        'article': {
            'subject': task.title,
            'body': task.description or task.title,
            'type': 'note',
            'internal': False,
        },
    })

    zammad_ticket_id = zammad_ticket['id']

    for ticket in task.tickets.select_related('assigned_to').all():
        duration = None
        if ticket.started_at and ticket.finished_at:
            duration = str(ticket.finished_at - ticket.started_at)

        body = f'IT Worker: {ticket.assigned_to.get_full_name() or ticket.assigned_to.username}\n'
        body += f'Status: {ticket.status}\n'
        if duration:
            body += f'Duration: {duration}\n'
        if ticket.notes:
            body += f'\nNotes:\n{ticket.notes}'

        client.post('/ticket_articles', {
            'ticket_id': zammad_ticket_id,
            'subject': f'Ticket by {ticket.assigned_to.username}',
            'body': body,
            'type': 'note',
            'internal': True,
        })

    task.zammad_synced = True
    task.save(update_fields=['zammad_synced'])
