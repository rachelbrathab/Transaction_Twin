# Transaction Twin — Backend

FastAPI backend for the Transaction Twin risk control plane.

## Quick Start

```bash
# Install dependencies
pip install -e ".[dev]"

# Copy environment config
cp ../.env.example .env

# Run the server
uvicorn app.main:app --reload --port 8000

# Open API docs
open http://localhost:8000/docs
```

## Structure

```
backend/
├── app/
│   ├── api/v1/endpoints/   # API route handlers
│   ├── core/                # Config, database, logging, errors
│   ├── db/                  # Database utilities
│   ├── models/              # SQLAlchemy ORM models
│   ├── schemas/             # Pydantic request/response schemas
│   ├── services/            # Business logic layer
│   └── main.py              # Application entry point
├── alembic/                 # Database migrations
├── tests/                   # Test suite
└── pyproject.toml           # Project configuration
```

## Testing

```bash
pytest -v                    # Run all tests
pytest tests/test_health.py  # Run specific test file
ruff check .                 # Lint
```

## Database Migrations

```bash
alembic revision --autogenerate -m "description"  # Create migration
alembic upgrade head                               # Apply migrations
alembic downgrade -1                               # Rollback one step
```
