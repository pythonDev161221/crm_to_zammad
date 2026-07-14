import gzip
import os
import subprocess
import tempfile
from datetime import date

import requests
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Backup PostgreSQL database and send to Telegram channel'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force', action='store_true',
            help='Run even when DEBUG=True (for local testing)',
        )

    def handle(self, *args, **options):
        if settings.DEBUG and not options['force']:
            self.stdout.write('Skipping backup — dev environment (DEBUG=True), use --force to override')
            return

        chat_id = getattr(settings, 'BACKUP_TELEGRAM_CHAT_ID', '')
        token = getattr(settings, 'BACKUP_TELEGRAM_BOT_TOKEN', '') or settings.TELEGRAM_BOT_TOKEN
        if not chat_id or not token:
            self.stderr.write('BACKUP_TELEGRAM_CHAT_ID or TELEGRAM_BOT_TOKEN not set')
            return

        db = settings.DATABASES['default']
        filename = f'backup_{date.today()}.sql.gz'
        tmp_path = os.path.join(tempfile.gettempdir(), filename)

        try:
            self._dump(db, tmp_path)
            size_mb = round(os.path.getsize(tmp_path) / (1024 * 1024), 2)
            self._send_file(token, chat_id, tmp_path, filename)
            self._send_message(token, chat_id, f'Backup done — {date.today()}, {size_mb} MB')
            self.stdout.write(f'Backup sent: {filename} ({size_mb} MB)')
        except Exception as exc:
            self.stderr.write(f'Backup failed: {exc}')
            self._send_message(token, chat_id, f'Backup FAILED — {date.today()}: {exc}')
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def _dump(self, db, path):
        env = os.environ.copy()
        env['PGPASSWORD'] = db.get('PASSWORD', '')
        cmd = [
            'pg_dump',
            '-h', db.get('HOST', 'localhost'),
            '-p', str(db.get('PORT', 5432)),
            '-U', db.get('USER', 'postgres'),
            db.get('NAME', ''),
        ]
        result = subprocess.run(cmd, env=env, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode())
        with gzip.open(path, 'wb') as f:
            f.write(result.stdout)

    def _send_file(self, token, chat_id, path, filename):
        with open(path, 'rb') as f:
            resp = requests.post(
                f'https://api.telegram.org/bot{token}/sendDocument',
                data={'chat_id': chat_id},
                files={'document': (filename, f, 'application/gzip')},
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
