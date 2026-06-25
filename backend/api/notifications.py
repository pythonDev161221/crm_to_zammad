import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def _send(telegram_id: int, text: str) -> None:
    token = settings.TELEGRAM_BOT_TOKEN
    if not token or not telegram_id:
        return
    try:
        requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={'chat_id': telegram_id, 'text': text},
            timeout=5,
        )
    except Exception as exc:
        logger.warning('Telegram notification failed: %s', exc)


def notify_task_assigned(task) -> None:
    assignee = task.assigned_to
    if not assignee.telegram_id:
        return
    delegator = task.created_by
    ticket = task.ticket
    text = (
        f'You have been assigned a new task.\n'
        f'Ticket #{ticket.id}: {ticket.title}\n'
        f'Delegated by: {delegator.get_full_name() or delegator.username}'
    )
    _send(assignee.telegram_id, text)


def notify_task_cancelled(task) -> None:
    assignee = task.assigned_to
    if not assignee.telegram_id:
        return
    delegator = task.created_by
    ticket = task.ticket
    text = (
        f'Your task has been cancelled.\n'
        f'Ticket #{ticket.id}: {ticket.title}\n'
        f'Cancelled by: {delegator.get_full_name() or delegator.username}'
    )
    _send(assignee.telegram_id, text)


def notify_ticket_created(ticket) -> None:
    from users.models import User
    company = ticket.station.company
    recipients = User.objects.filter(
        role__in=[User.Role.IT_MANAGER, User.Role.IT_DEPUTY, User.Role.IT_WORKER],
        companies=company,
        is_active=True,
    ).exclude(telegram_id__isnull=True).exclude(telegram_id=0)
    reporter = ticket.created_by
    station = ticket.station
    text = (
        f'New ticket #{ticket.id}: {ticket.title}\n'
        f'Station: {station.name}\n'
        f'Reporter: {reporter.get_full_name() or reporter.username}'
    )
    for user in recipients:
        _send(user.telegram_id, text)
