#!/usr/bin/env bash
#
# Transaction Twin — Production Migration Runner
#
# Runs Alembic migrations against the production database.
# Designed to be run once before starting the application.
#
# Usage:
#   docker compose -f docker-compose.prod.yml run --rm backend python scripts/run_migrations.sh
#   or
#   bash scripts/run_migrations.sh
#
# Requirements:
#   - DATABASE_URL environment variable must be set
#   - alembic must be available in PATH
#
set -euo pipefail

echo "=== Transaction Twin — Database Migration ==="
echo "DATABASE_URL: ${DATABASE_URL:-not set}"
echo ""

# Validate DATABASE_URL is set
if [ -z "${DATABASE_URL:-}" ]; then
    echo "ERROR: DATABASE_URL is not set."
    echo "Set it to your PostgreSQL connection string."
    echo "Example: postgresql+asyncpg://user:password@host:5432/dbname"
    exit 1
fi

# Run migrations
echo "Running migrations..."
alembic upgrade head

echo ""
echo "Migration complete."
echo ""

# Show current migration state
alembic current

echo ""
echo "=== Done ==="
