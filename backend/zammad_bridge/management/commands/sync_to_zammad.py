from django.core.management.base import BaseCommand
from tasks.models import Task
from zammad_bridge.client import push_to_zammad


class Command(BaseCommand):
    help = 'Retry pushing unsynced resolved tasks to Zammad'

    def handle(self, *args, **options):
        tasks = Task.objects.filter(status=Task.Status.RESOLVED, zammad_synced=False)
        total = tasks.count()

        if total == 0:
            self.stdout.write('No unsynced tasks found.')
            return

        self.stdout.write(f'Found {total} unsynced task(s). Syncing...')

        success = 0
        for task in tasks:
            try:
                push_to_zammad(task)
                success += 1
                self.stdout.write(f'  OK: Task #{task.pk} - {task.title}')
            except Exception as e:
                self.stderr.write(f'  FAIL: Task #{task.pk} - {e}')

        self.stdout.write(f'Done. {success}/{total} synced.')
