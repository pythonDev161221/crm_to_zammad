from django.db import migrations, models


def backfill_created_at(apps, schema_editor):
    Task = apps.get_model('tasks', 'Task')
    for task in Task.objects.select_related('ticket').filter(created_at__isnull=True):
        task.created_at = task.ticket.created_at
        task.save(update_fields=['created_at'])


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0010_education_item'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='created_at',
            field=models.DateTimeField(null=True),
        ),
        migrations.RunPython(backfill_created_at, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='task',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True),
        ),
    ]
