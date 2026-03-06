from django.core.management.base import BaseCommand
from tasks.models import Ticket
from zammad_bridge.client import push_to_zammad


class Command(BaseCommand):
    help = 'Retry pushing unsynced resolved tickets to Zammad'

    def handle(self, *args, **options):
        tickets = Ticket.objects.filter(status=Ticket.Status.RESOLVED, zammad_synced=False)
        total = tickets.count()

        if total == 0:
            self.stdout.write('No unsynced tickets found.')
            return

        self.stdout.write(f'Found {total} unsynced ticket(s). Syncing...')

        success = 0
        for ticket in tickets:
            try:
                push_to_zammad(ticket)
                success += 1
                self.stdout.write(f'  OK: Ticket #{ticket.pk} - {ticket.title}')
            except Exception as e:
                self.stderr.write(f'  FAIL: Ticket #{ticket.pk} - {e}')

        self.stdout.write(f'Done. {success}/{total} synced.')
