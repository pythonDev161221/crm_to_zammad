import os
import tempfile
from calendar import monthrange
from datetime import date

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from openpyxl import Workbook
from openpyxl.styles import Font

from tasks.models import Task, Ticket


class Command(BaseCommand):
    help = 'Send monthly Excel report of tickets and tasks to Telegram channel'

    def handle(self, *args, **options):
        if settings.DEBUG:
            self.stdout.write('Skipping report — dev environment (DEBUG=True)')
            return

        chat_id = getattr(settings, 'BACKUP_TELEGRAM_CHAT_ID', '')
        token = settings.TELEGRAM_BOT_TOKEN
        if not chat_id or not token:
            self.stderr.write('BACKUP_TELEGRAM_CHAT_ID or TELEGRAM_BOT_TOKEN not set')
            return

        today = date.today()
        # Previous month
        first_of_this_month = today.replace(day=1)
        last_month = first_of_this_month.replace(day=1)
        if first_of_this_month.month == 1:
            last_month = last_month.replace(year=today.year - 1, month=12)
        else:
            last_month = last_month.replace(month=first_of_this_month.month - 1)
        last_day = monthrange(last_month.year, last_month.month)[1]
        period_start = last_month
        period_end = last_month.replace(day=last_day)

        label = last_month.strftime('%Y-%m')
        filename = f'report_{label}.xlsx'
        tmp_path = os.path.join(tempfile.gettempdir(), filename)

        try:
            self._build_excel(tmp_path, period_start, period_end)
            self._send_file(token, chat_id, tmp_path, filename)
            self._send_message(token, chat_id, f'Monthly report — {label} sent.')
            self.stdout.write(f'Report sent: {filename}')
        except Exception as exc:
            self.stderr.write(f'Report failed: {exc}')
            self._send_message(token, chat_id, f'Monthly report FAILED — {label}: {exc}')
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def _build_excel(self, path, period_start, period_end):
        wb = Workbook()

        # --- Tickets sheet ---
        ws_tickets = wb.active
        ws_tickets.title = 'Tickets'
        ticket_headers = [
            'ID', 'Title', 'Description', 'Station', 'Company',
            'Status', 'Created By', 'Created At', 'Resolved By', 'Resolved At', 'Rating',
        ]
        ws_tickets.append(ticket_headers)
        for cell in ws_tickets[1]:
            cell.font = Font(bold=True)

        tickets = Ticket.objects.filter(
            created_at__date__gte=period_start,
            created_at__date__lte=period_end,
        ).select_related('created_by', 'resolved_by', 'station', 'station__company')

        for t in tickets:
            ws_tickets.append([
                t.id,
                t.title,
                t.description or '',
                t.station.name if t.station else '',
                t.station.company.name if t.station and t.station.company else '',
                t.status,
                t.created_by.get_full_name() or t.created_by.username,
                t.created_at.strftime('%Y-%m-%d %H:%M') if t.created_at else '',
                t.resolved_by.get_full_name() or t.resolved_by.username if t.resolved_by else '',
                t.resolved_at.strftime('%Y-%m-%d %H:%M') if t.resolved_at else '',
                t.rating if t.rating is not None else '',
            ])

        # --- Tasks sheet ---
        ws_tasks = wb.create_sheet('Tasks')
        task_headers = [
            'ID', 'Ticket ID', 'Ticket Title', 'Assigned To', 'Created By',
            'Status', 'Notes', 'Created At', 'Started At', 'Finished At',
        ]
        ws_tasks.append(task_headers)
        for cell in ws_tasks[1]:
            cell.font = Font(bold=True)

        tasks = Task.objects.filter(
            created_at__date__gte=period_start,
            created_at__date__lte=period_end,
        ).select_related('ticket', 'assigned_to', 'created_by')

        for t in tasks:
            ws_tasks.append([
                t.id,
                t.ticket.id,
                t.ticket.title,
                t.assigned_to.get_full_name() or t.assigned_to.username,
                t.created_by.get_full_name() or t.created_by.username if t.created_by else '',
                t.status,
                t.notes or '',
                t.created_at.strftime('%Y-%m-%d %H:%M') if t.created_at else '',
                t.started_at.strftime('%Y-%m-%d %H:%M') if t.started_at else '',
                t.finished_at.strftime('%Y-%m-%d %H:%M') if t.finished_at else '',
            ])

        wb.save(path)

    def _send_file(self, token, chat_id, path, filename):
        with open(path, 'rb') as f:
            resp = requests.post(
                f'https://api.telegram.org/bot{token}/sendDocument',
                data={'chat_id': chat_id},
                files={'document': (filename, f, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')},
                timeout=60,
            )
        if not resp.ok:
            raise RuntimeError(f'Telegram sendDocument failed: {resp.text}')

    def _send_message(self, token, chat_id, text):
        try:
            requests.post(
                f'https://api.telegram.org/bot{token}/sendMessage',
                json={'chat_id': chat_id, 'text': text},
                timeout=10,
            )
        except Exception as exc:
            self.stderr.write(f'Could not send status message: {exc}')
