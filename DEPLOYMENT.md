# Transaction Twin — Production Deployment Guide

## Prerequisites

- Docker Engine 24+ and Docker Compose v2+
- A domain name with DNS configured
- PostgreSQL 16+ (provided via Docker)
- Redis 7+ (provided via Docker)

## Quick Start

### 1. Configure Environment

```bash
cp .env.prod.example .env.prod
```

Edit `.env.prod` with your values. **At minimum, set:**

- `POSTGRES_PASSWORD` — generate with `openssl rand -base64 32`
- `JWT_SECRET_KEY` — generate with `python -c "import secrets; print(secrets.token_urlsafe(64))"`
- `DOMAIN` — your production domain (e.g., `app.example.com`)
- `CORS_ORIGINS` — your frontend URL (e.g., `https://app.example.com`)
- `NEXT_PUBLIC_API_URL` — your backend API URL (e.g., `https://app.example.com`)

### 2. Run Migrations

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm backend \
  alembic upgrade head
```

### 3. Start Services

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
```

### 4. Verify

```bash
# Check all services are healthy
docker compose -f docker-compose.prod.yml ps

# Check backend health
curl https://$DOMAIN/health

# Check frontend
curl https://$DOMAIN/
```

## Architecture

```
Internet
  ↓
Caddy (port 80/443) — TLS termination, security headers
  ├── /           → Frontend (Next.js, port 3000)
  ├── /api/*      → Backend (FastAPI, port 8000) — all API routes under /api/v1
  └── /health     → Backend (FastAPI, port 8000) — liveness check
        ↓
  PostgreSQL (port 5432, internal only)
  Redis (port 6379, internal only)
```

## Services

| Service | Port | Public? | Purpose |
|---------|------|---------|---------|
| Caddy | 80, 443 | ✅ | Reverse proxy, TLS |
| Frontend | 3000 | ❌ | Next.js SPA |
| Backend | 8000 | ❌ | FastAPI API |
| PostgreSQL | 5432 | ❌ | Database |
| Redis | 6379 | ❌ | Rate limiter |

## Database Migration

### Running Migrations

Migrations run via Alembic inside the backend container:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm backend \
  alembic upgrade head
```

### Migration Strategy

- Migrations are run **once** before the application starts.
- **Do not** run migrations from every backend replica simultaneously.
- Alembic handles concurrency-safe migration locking.
- Migrations 001–006 are current.

### Creating New Migrations

```bash
# Inside the backend container
alembic revision --autogenerate -m "description of change"
```

**Never** auto-generate migrations in production. Generate locally, test, then deploy.

## Backup & Restore

### Creating Backups

```bash
# Full backup
docker compose -f docker-compose.prod.yml --env-file .env.prod exec postgres \
  pg_dump -U $POSTGRES_USER $POSTGRES_DB > backup_$(date +%Y%m%d_%H%M%S).sql

# Backup with compression
docker compose -f docker-compose.prod.yml --env-file .env.prod exec postgres \
  pg_dump -U $POSTGRES_USER $POSTGRES_DB | gzip > backup_$(date +%Y%m%d_%H%M%S).sql.gz
```

### Restoring Backups

```bash
# Restore from backup
docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T postgres \
  psql -U $POSTGRES_USER $POSTGRES_DB < backup.sql

# Restore from compressed backup
docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T postgres \
  zcat backup.sql.gz | psql -U $POSTGRES_USER $POSTGRES_DB
```

### Backup Recommendations

- **Frequency**: Daily at minimum, before any migration
- **Retention**: Keep at least 7 daily backups and 4 weekly backups
- **Storage**: Off-site (S3, GCS, or equivalent)
- **Test**: Restore backups to verify they work
- **⚠️ WARNING**: Never commit backup files to Git

## Health Checks

All services have health checks configured:

```bash
# Check all service health
docker compose -f docker-compose.prod.yml ps

# Backend health endpoint
curl https://$DOMAIN/health

# Backend readiness (includes DB check)
curl https://$DOMAIN/api/v1/health
```

## HTTPS / TLS

Caddy handles TLS automatically via Let's Encrypt:

1. Set `DOMAIN` in `.env.prod`
2. Ensure port 80 and 443 are open
3. Ensure DNS A record points to your server
4. Caddy will automatically obtain and renew TLS certificates

### Manual Certificate

If you have existing certificates:

1. Place `cert.pem` and `key.pem` in `./certs/`
2. Update the Caddyfile to use your certificates
3. Restart Caddy

## Troubleshooting

### Services won't start

```bash
# Check logs
docker compose -f docker-compose.prod.yml logs backend
docker compose -f docker-compose.prod.yml logs frontend
docker compose -f docker-compose.prod.yml logs postgres
docker compose -f docker-compose.prod.yml logs caddy
```

### Database connection issues

```bash
# Test PostgreSQL connectivity
docker compose -f docker-compose.prod.yml exec postgres pg_isready -U transaction_twin

# Check if migrations have run
docker compose -f docker-compose.prod.yml exec postgres \
  psql -U transaction_twin -d transaction_twin -c "\dt"
```

### Authentication issues

- Ensure `JWT_SECRET_KEY` is set and ≥32 characters
- Ensure `APP_ENV=production` is set
- Check backend logs for startup validation errors

### TLS issues

- Ensure ports 80 and 443 are open
- Ensure DNS A record is correct
- Check Caddy logs: `docker compose logs caddy`
- Caddy stores certificates in the `caddy_data` volume

## Rollback Procedure

If a new deployment has issues:

1. **Stop the new version**:
   ```bash
   docker compose -f docker-compose.prod.yml down
   ```

2. **Restore database** (if migration was applied):
   ```bash
   docker compose -f docker-compose.prod.yml exec -T postgres \
     psql -U $POSTGRES_USER $POSTGRES_DB < backup_before_migration.sql
   ```

3. **Start the previous version**:
   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
   ```

4. **Verify**:
   ```bash
   docker compose -f docker-compose.prod.yml ps
   curl https://$DOMAIN/health
   ```

## Security Notes

- **Never** commit `.env.prod` to Git
- **Never** use the development JWT secret in production
- **Never** expose PostgreSQL or Redis to the public internet
- **Always** use HTTPS in production
- **Always** use strong, unique passwords
- **Rotate** the JWT secret if it may have been compromised
- **Back up** the database before any migration
