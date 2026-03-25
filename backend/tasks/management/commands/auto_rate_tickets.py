from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from tasks.models import Ticket


class Command(BaseCommand):
    help = 'Auto-rate resolved tickets that have not been rated within 1 day (sets rating=2)'

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=1)
        updated = Ticket.objects.filter(
            status=Ticket.Status.RESOLVED,
            rating__isnull=True,
            resolved_at__lt=cutoff,
        ).update(rating=2)
        self.stdout.write(f'Auto-rated {updated} ticket(s) with 2 stars.')
