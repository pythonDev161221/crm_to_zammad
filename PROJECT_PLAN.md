# CRM to Zammad - Project Plan

## Overview
Internal tech support system. Workers report problems via Telegram Mini App.
IT Workers manage and resolve them. Resolved tickets archive to Zammad for analytics.

---

## Stack

| Part | Technology |
|---|---|
| Backend | Django + DRF + PostgreSQL |
| Auth | JWT via Telegram initData (workers) / username+password (staff) |
| Frontend | Telegram Mini App (vanilla JS) |
| Archive | Zammad (live mirror for agents/groups + snapshot archive for tickets) |
| Async | None — synchronous Zammad push + management command for retries |

---

## Repository Structure

```
crm_to_zammad/
├── backend/
│   ├── config/            # settings, urls, wsgi
│   ├── users/             # User, Station, Company models
│   ├── tasks/             # Ticket, Task, Comment, CommentPhoto models
│   ├── zammad_bridge/     # Zammad API client, push logic, agent sync
│   └── api/               # DRF serializers, views, urls, permissions
├── miniapp/
│   └── src/               # index.html, app.js, api.js, style.css
└── docs/
```

---

## User Roles

| Role | Permissions |
|---|---|
| Admin | Full access, manage all users, companies, stations via Django Admin |
| Station Manager | Manage workers at their station(s), add/remove deputies |
| IT Worker | Handle tasks within tickets, delegate, resolve |
| Worker | Report problems, view own tickets, comment |

---

## Core Models

### Company
```
- id
- name          must match Zammad Group name exactly
```

### Station
```
- id
- name          must match Zammad Organization name exactly
- company       FK → Company
- manager       FK → User (one manager can manage many stations)
- deputies      M2M → User (many deputies per station)
```

### User
```
- id
- role          admin / station_manager / it_worker / worker
- telegram_id   for Telegram auth (nullable)
- station       FK → Station (for workers)
- companies     M2M → Company (for IT workers only, assigned by admin)
                IT worker with no companies = no access to any tickets
```

### Ticket  ← maps to Zammad Ticket
```
- id
- created_by    FK → Worker
- title
- description
- status        open / in_progress / resolved
- zammad_synced bool (default False)
- created_at
- resolved_at
```

### Task  ← maps to Zammad Article (internal)
```
- id
- ticket        FK → Ticket
- assigned_to   FK → IT Worker
- status        open / in_progress / done
- notes
- started_at    set automatically on in_progress
- finished_at   set automatically on done
```

### Comment  ← maps to Zammad Article
```
- id
- ticket        FK → Ticket
- author        FK → User
- text          (blank allowed for photo-only comments)
- is_internal   bool — if True: IT staff only, not visible to workers
- created_at
```

### CommentPhoto
```
- id
- comment       FK → Comment
- image         ImageField → /media/comments/
```

---

## Visibility Rules

| Role | Sees |
|---|---|
| Worker | Only their own tickets |
| IT Worker | Open tickets from their companies' stations + tickets they have a task in |
| Station Manager | All tickets |
| Admin | All tickets |

- Workers never see `is_internal=True` comments
- IT workers assigned to no companies cannot see any open tickets

---

## Workflow

```
1. Worker reports problem
   → Ticket created (status: open)

2. IT Worker sees open ticket (filtered by their company)
   → Takes it: Task created assigned to themselves (status: open)

3. IT Worker needs help
   → Delegates: creates Task for another IT Worker in same Ticket
   → Both can now see the full Ticket + all Tasks + all Comments

4. Workers and IT workers chat via Comments
   → Workers post public comments (photos allowed)
   → IT workers post internal or public comments (photos allowed)

5. All Tasks done → IT Worker resolves Ticket
   → Synchronous push to Zammad

6. Analytics workers read Zammad for productivity reports
```

---

## Zammad Integration

### Ticket push (on resolve)
```
Ticket resolved
    ↓
push_to_zammad(ticket)
    ↓
get_or_create Group (= Company name)
get_or_create Organization (= Station name)
    ↓
POST /api/v1/tickets        → Zammad Ticket (group=company, org=station)
POST /api/v1/ticket_articles → one Article per Task (internal=True)
POST /api/v1/ticket_articles → one Article per Comment (internal matches is_internal)
    ↓
Success → ticket.zammad_synced = True
Fail    → ticket.zammad_synced = False
    ↓
Retry: python manage.py sync_to_zammad
```

### Zammad mapping
| Our model | Zammad concept |
|---|---|
| Company | Group |
| Station | Organization |
| Worker | Customer |
| IT Worker | Agent |
| Ticket | Ticket |
| Task | Article (internal) |
| Comment | Article (internal or public) |

### Agent sync (live mirror)
- When IT worker created in Django Admin → Agent created in Zammad
- When IT worker's companies change → Agent's Zammad group membership updated
- Failures show WARNING in Django Admin, do not block the save

---

## API Endpoints

| Method | URL | Description |
|---|---|---|
| GET/POST | `/api/tickets/` | List / create tickets |
| GET | `/api/tickets/<id>/` | Ticket detail |
| POST | `/api/tickets/<id>/resolve/` | Resolve ticket → push to Zammad |
| POST | `/api/tickets/<id>/tasks/` | Create task (IT worker takes / delegates) |
| PATCH | `/api/tasks/<id>/` | Update task status |
| POST | `/api/tickets/<id>/comments/` | Add comment (multipart, supports photos) |
| GET | `/api/it-workers/?ticket_id=X` | List IT workers eligible for ticket |
| GET/POST | `/api/station/workers/` | List / add station workers |
| DELETE | `/api/station/workers/<id>/` | Deactivate station worker |
| POST | `/api/auth/change-password/` | Change own password |
| GET | `/api/me/` | Current user info |

---

## Telegram Mini App Screens

| Screen | Role |
|---|---|
| Ticket list | All roles |
| Ticket detail | All roles |
| Create ticket | Worker only |
| Delegate task | IT Worker only |
| Station workers | Station Manager only |
| Add worker | Station Manager only |
| Change password | All roles |

---

## Dev / Testing

- Dev login: `http://localhost:8000/dev/` (DEBUG=True only)
- Test users: `admin_user`, `manager1` (AZS-1), `it_worker1`, `it_worker2`, `worker1`, `worker2`
- Start server: `cd backend && ~/.local/bin/pipenv run python manage.py runserver`
- Retry Zammad push: `pipenv run python manage.py sync_to_zammad`

---

## What Is NOT Done Yet

- Telegram Bot registration and Mini App URL setup
- VPS deployment / production setup (Nginx, gunicorn, HTTPS, env vars)
- Real Zammad credentials (`ZAMMAD_URL`, `ZAMMAD_TOKEN` in `.env`)
- Deputy management UI in Mini App (currently admin-only via Django Admin)
- Task photo on ticket creation (photos only in comments for now)
