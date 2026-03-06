import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0003_comment_is_internal_alter_comment_text_commentphoto'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Swap model names via a temp name
        migrations.RenameModel('Task', 'OldTask'),
        migrations.RenameModel('Ticket', 'Task'),
        migrations.RenameModel('OldTask', 'Ticket'),

        # Rename FK fields
        migrations.RenameField('Task', 'task', 'ticket'),
        migrations.RenameField('Comment', 'task', 'ticket'),

        # Fix related_names and FK targets
        migrations.AlterField(
            model_name='ticket',
            name='created_by',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='tickets',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name='task',
            name='assigned_to',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='tasks',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name='task',
            name='ticket',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='tasks',
                to='tasks.ticket',
            ),
        ),
        migrations.AlterField(
            model_name='comment',
            name='ticket',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='comments',
                to='tasks.ticket',
            ),
        ),
    ]
