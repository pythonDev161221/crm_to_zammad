#!/bin/bash
cd "$(dirname "$0")"
docker compose exec -T backend python manage.py backup_to_telegram >> /var/log/backup_telegram.log 2>&1
