# Deployment Guide

## Prerequisites

- Docker and Docker Compose installed on the server
- A domain or IP for the backend (e.g. `api.yourdomain.com`)
- A domain or IP for the frontend (e.g. `app.yourdomain.com`)

## 1. Clone the repo

```bash
git clone <repo-url>
cd powerling-preaudit
```

## 2. Configure environment variables

**Backend** — copy the example and fill in real values:

```bash
cp backend/.env.example backend/.env
```

Edit `backend/.env`:

```
OPENAI_API_KEY=sk-...
DATAFORSEO_LOGIN=your_dataforseo_email
DATAFORSEO_PASSWORD=your_dataforseo_password
YOUTUBE_API_KEY=AIza...
GOOGLE_PAGESPEED_API_KEY=AIza...
FRONTEND_ORIGIN=https://app.yourdomain.com
```

**Frontend** — the API URL is baked in at build time via Docker build args. Set it in a `.env` file at the repo root:

```bash
echo "NEXT_PUBLIC_API_URL=https://api.yourdomain.com" > .env
```

## 3. Create the database file

Docker will create a directory instead of a file if this doesn't exist yet:

```bash
touch backend/audit_jobs.db
```

## 4. Build and start

```bash
docker compose up --build -d
```

- Frontend: `http://localhost:3000`
- Backend: `http://localhost:8000`

## 5. Verify

```bash
docker compose logs -f
```

Both containers should start without errors. Hit `http://localhost:8000/docs` to confirm the backend API is live.

## Updating

```bash
git pull
docker compose up --build -d
```

This rebuilds both images and restarts the containers. Any jobs that were `processing` at restart are automatically reset to `error` on startup.

## Notes

- The SQLite database is stored at `backend/audit_jobs.db` on the host, bind-mounted into the container. It persists across restarts and rebuilds.
- At most 2 audits run concurrently. Additional requests queue behind a semaphore.
- Logs: `docker compose logs backend` / `docker compose logs frontend`
