# NexaWork

**Connect. Collaborate. Work smarter.**

NexaWork is a modular Django workplace collaboration MVP for one company per installation, with employees across teams and branches. The code is organized into Django apps for accounts, organization, communications, documents, and the workplace assistant.

## What works in this MVP

- Employee ID and password sign-in, plus a separate employer sign-in.
- Single-company administration for branches, regions, departments, teams, job roles, and employees.
- Organization-wide and membership-restricted channels with real-time WebSocket messaging, automatic reconnects, and message-history catch-up.
- Administrator channel archiving and restoration, preserving archived channel history as read-only.
- Branch-aware announcements and per-user notifications.
- Meeting scheduling, real-time participant chat, participant roles, host/co-host controls, meeting locks, participant muting, and host/admin removal with a 10-minute rejoin restriction.
- Optional LiveKit integration for browser audio/video, short-lived room tokens, provider-side participant controls, and webhook-driven meeting state.
- Organization/branch-scoped file library, restricted-file access lists, uploads capped at 25 MB, and authenticated download views.
- A workplace assistant that answers common platform questions and stores each user's recent exchanges.
- Django admin and configurable role/permission management for the company's employer-side administration.
- Celery tasks for meeting reminders and notification email, with Redis-backed Channels support.

The assistant uses built-in guidance in this MVP; no external AI provider is called. Channel messages use authenticated WebSockets when connected and fall back to authenticated message-history polling while reconnecting. Notifications also use authenticated database polling as a fallback when a WebSocket connection or shared channel layer is unavailable. Meeting state and access authorization are managed by Django. When LiveKit is configured, audio/video travels through LiveKit rather than Django, and server-side participant removal/muting is available. If an external provider URL is used instead, NexaWork cannot enforce provider-side participant removal or rejoin restrictions.

Uploaded files are stored locally under `private_media/` by default and are never exposed using a public media URL. Django's storage backend is configurable with `DJANGO_FILE_STORAGE_BACKEND`; production can select a private S3-compatible backend while continuing to use the same authorized download view.

The Files page keeps previous file contents when an authorized user uploads a new version; earlier versions can be viewed and downloaded from each file's version history. Run `python scripts/backup.py` to save a database snapshot and a copy of local private uploads under `backups/`. The script retains 30 days of backups by default; set `BACKUP_DIR` or `BACKUP_RETENTION_DAYS` to change those defaults. Schedule the command with your operating system's task scheduler for regular backups. If you configure remote object storage, back up that storage separately. These backups are on the same host and are not protection against host or disk loss; copy them to separate storage for disaster recovery. Protect the backup directory because it contains private files and database data.

## Run locally

Requires Python 3.10+ and pip.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000), sign in at the employer sign-in using the superuser created above, and complete the one-time company setup. That account becomes the company's employer administrator. Create employees from **Manage → Employees**; employees sign in at `/login/`. Each installation supports one company; use a separate installation and database for another company.

## Employee account invitations

Create employee accounts from **Manage → Employees → Add employee** and provide the employee's email address. NexaWork sends a one-time setup link that expires after three days; the employee chooses their own password using that link. Administrators do not set or receive employee passwords. If an invitation expires or needs to be resent, use **Resend invite** in the Employees list; doing so invalidates the previous link. Local settings are loaded from `.env` (ignored by Git); `.env.example` is a reference for configuring environment variables in production. For Brevo SMTP, use `smtp-relay.brevo.com` on port `587` with TLS. Set `EMAIL_HOST_USER` to the SMTP login shown in Brevo, `EMAIL_HOST_PASSWORD` to a Brevo SMTP key (not an API key), and `DEFAULT_FROM_EMAIL` to a sender address verified in Brevo. Never commit `.env` or share its SMTP key.

The default database is SQLite. Set `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, and `POSTGRES_PORT` to use PostgreSQL. Set a strong `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=false`, and production `DJANGO_ALLOWED_HOSTS` before deployment. With debug disabled, HTTPS redirects, secure session/CSRF cookies, and HSTS are enabled by default; configure the reverse proxy to terminate TLS correctly.

## Services

The default setup uses SQLite and private files on the local filesystem. Start the included Redis service with `docker compose up -d redis`; it is exposed only on localhost and persists its data in a Docker volume. The sample `.env.example` already points `REDIS_URL`, `CELERY_BROKER_URL`, and `CELERY_RESULT_BACKEND` at this service. Copy or set those values in the environment used to launch Django. Redis is required for live notifications across multiple application processes; without it, the in-memory channel layer only reaches connections handled by the same process, while authenticated polling remains a fallback. In production, set `REDIS_URL` to a secured Redis service reachable by all Django/Daphne processes and Celery workers; do not expose an unauthenticated Redis port publicly.

To use PostgreSQL, install and start PostgreSQL separately, then export the `POSTGRES_*` environment variables. Run the Celery worker and scheduler in separate terminals with `celery -A QueshStandards worker --loglevel=info` and `celery -A QueshStandards beat --loglevel=info`; the scheduler checks for due announcements every 5 seconds. Integrated meeting audio/video is optional; install and run a LiveKit server separately and export its URL and credentials. Django loads a local `.env` file when present; production environment variables should be configured by the process manager.

## Deploy a free Render demo

The root `render.yaml` defines a free Render Blueprint with a Django ASGI web service, PostgreSQL, and Redis-compatible Key Value. After pushing the repository to GitHub, create a Blueprint in the Render Dashboard, connect this repository and branch, review the resources, and choose **Deploy Blueprint**. Render will then deploy each new commit to the linked branch automatically. Render does not receive values from the local `.env` file.

The Blueprint asks for an initial employer's `DJANGO_SUPERUSER_EMPLOYEE_ID` and `DJANGO_SUPERUSER_PASSWORD` in Render; choose a strong password there, not in Git or chat. Render creates that account once after the first successful deploy. Remove `DJANGO_SUPERUSER_PASSWORD` from the service's environment after the initial deploy hook succeeds. The Blueprint also asks for `EMAIL_HOST_USER` and `EMAIL_HOST_PASSWORD` so SMTP credentials can be entered privately. The sample uses port `2525`; confirm that your email provider supports it. Configure LiveKit credentials in Render separately if you want audio/video.

This free configuration is for a demo, not reliable production use: the web service can sleep, local private uploads are lost on restarts or deploys, free Postgres expires after 30 days, and free Key Value data can be lost on restarts. It does not run the Celery worker or scheduler, so scheduled announcements and meeting reminders will not run reliably. Render's free web services also block common SMTP ports `25`, `465`, and `587`. For reliable full functionality, use paid always-on services, persistent private object storage, and a Celery worker plus scheduler.

## Tests and checks

```bash
python manage.py check
python manage.py test
```
