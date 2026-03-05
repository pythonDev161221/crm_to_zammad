import requests
from django.conf import settings


class ZammadClient:
    def __init__(self):
        self.base_url = settings.ZAMMAD_URL.rstrip('/')
        self.headers = {
            'Authorization': f'Token token={settings.ZAMMAD_TOKEN}',
            'Content-Type': 'application/json',
        }

    def post(self, endpoint, data):
        url = f'{self.base_url}/api/v1{endpoint}'
        response = requests.post(url, json=data, headers=self.headers, timeout=10)
        response.raise_for_status()
        return response.json()


def push_to_zammad(task):
    client = ZammadClient()

    zammad_ticket = client.post('/tickets', {
        'title': task.title,
        'group': 'Users',
        'customer': task.created_by.email or task.created_by.username,
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
