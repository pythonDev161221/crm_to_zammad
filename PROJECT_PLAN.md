# CRM to Zammad - Project Plan

## Overview
Internal tech support system. Workers report problems via Telegram Mini App.
IT Workers manage and resolve them in Django. Resolved tasks archive to Zammad for analytics.

---

## Stack

| Part | Technology |
|---|---|
| Backend | Django + DRF + PostgreSQL |
| Auth | JWT via Telegram initData |
| Frontend | Telegram Mini App |
| Archive | Zammad (write-only) |
| Async | None (synchronous Zammad push) |

---

## Repository Structure

```
crm_to_zammad/
├── backend/
│   ├── config/            # settings, urls, wsgi
│   ├── users/             # User model + roles
│   ├── tasks/             # Task + Ticket + Comment models
│   ├── zammad_bridge/     # Zammad API client + push logic
│   └── api/               # DRF serializers, views, routers
├── miniapp/               # Telegram Mini App (HTML/JS or React)
│   └── src/
└── docs/
```

---

## User Roles

| Role | Permissions |
|---|---|
| Admin | Full access, manage all users |
| Station Manager | Manage workers at their station |
| IT Worker | Handle tickets within tasks, create child tickets |
| Worker | Report problems, view own tasks and comments |

---

## Core Models

### Task
```
- id
- created_by       FK → Worker
- title
- description
- status           open / in_progress / resolved
- zammad_synced    bool (default False)
- created_at
- resolved_at
```

### Ticket
```
- id
- task             FK → Task
- assigned_to      FK → IT Worker
- status           open / in_progress / done
- notes
- started_at
- finished_at
```

### Comment
```
- id
- task             FK → Task
- author           FK → User
- text
- created_at
```

---

## Visibility Rule
- Worker who created a Task can always see it and all its Tickets
- IT Worker can see a Task only if they own a Ticket within it
- IT Worker C (no Ticket in Task X) cannot see Task X

---

## Workflow

```
1. Worker reports problem
   → Task created (status: open)

2. IT Worker A assigned a Ticket in that Task
   → Task status: in_progress

3. IT Worker A needs help
   → Creates Ticket for IT Worker B in same Task
   → Both A and B can now see full Task + all Tickets

4. Workers comment, update notes, mark Tickets done

5. All Tickets done → IT Worker A resolves Task
   → Synchronous push to Zammad

6. Analytics workers read Zammad for productivity reports
```

---

## Zammad Integration

```
Task resolved
    ↓
push_to_zammad(task)
    ↓
POST /api/v1/tickets        → creates Zammad Ticket from Task
POST /api/v1/ticket_articles → one Article per Ticket (per IT Worker)
    ↓
Success → task.zammad_synced = True
Fail    → task.zammad_synced = False
    ↓
Retry: python manage.py sync_to_zammad
```

Zammad is a **snapshot at resolution time**. Not a live mirror.
Django is always the source of truth.

---

## Telegram Mini App

- Worker opens Mini App in Telegram
- Django validates Telegram `initData`, issues JWT
- Workers: see tasks, report new problems, read comments
- No passwords needed for workers

---

## Build Phases

### Phase 1 - Backend foundation
- [ ] Django project scaffold
- [ ] User model with roles
- [ ] Task + Ticket + Comment models
- [ ] Admin panel

### Phase 2 - API
- [ ] DRF endpoints for Tasks, Tickets, Comments
- [ ] JWT auth via Telegram initData
- [ ] Permissions per role

### Phase 3 - Zammad bridge
- [ ] Zammad API client
- [ ] push_to_zammad service
- [ ] sync_to_zammad management command

### Phase 4 - Telegram Mini App
- [ ] UI for Workers (report, view, comment)
- [ ] UI for IT Workers (manage tickets)

### Phase 5 - Station Manager & Admin views
- [ ] Station Manager dashboard
- [ ] Admin panel customization
