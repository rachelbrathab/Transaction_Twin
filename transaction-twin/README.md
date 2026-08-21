# Transaction Twin — The Trust Layer for AI Payments

## Problem Statement

AI agents can perform transactions that are technically valid but no longer match the user's original intent, spending policy, agent authorization, or expected transaction context.

Transaction Twin is an intent-aware risk control plane for AI-initiated payments that evaluates:

```
User Intent → Agent Identity → Agent Actions → Transaction → Policy → Risk → Decision
```

## Architecture Overview

```
Frontend (Next.js)
   ↓
REST API (FastAPI /api/v1)
   ↓
Services Layer
   ↓
Database (PostgreSQL via SQLAlchemy)
```

### Future Components

```
Intent Engine          — Natural-language user intent extraction
Transaction Twin       — Expected transaction state tracking
Risk Engine            — ML-based risk scoring
Policy Engine          — Deterministic policy enforcement (ALLOW / REVIEW / STEP-UP / BLOCK)
Agent Simulator        — Synthetic agent behavior simulation
Razorpay Integration   — Test mode payment processing
```

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js, TypeScript, React, Tailwind CSS |
| Backend | Python 3.12+, FastAPI, Pydantic v2 |
| Database | PostgreSQL 16, SQLAlchemy 2.x, Alembic |
| Testing | pytest, httpx (backend), ESLint (frontend) |
| DevOps | Docker Compose (PostgreSQL) |

## Local Setup

### Prerequisites

- Python 3.12+
- Node.js 18+
- npm
- Docker & Docker Compose (for PostgreSQL)

### 1. Start PostgreSQL

```bash
cd transaction-twin
docker compose up -d
```

### 2. Backend

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp ../.env.example .env

# Run migrations
alembic upgrade head

# Start the server
uvicorn app.main:app --reload --port 8000
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

### 4. Open

- Frontend: http://localhost:3000
- API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health

## Environment Variables

See `.env.example` for all supported variables.

| Variable | Description | Default |
|----------|-------------|---------|
| `APP_ENV` | Environment (development/testing/production) | development |
| `DATABASE_URL` | PostgreSQL connection string | localhost:5432 |
| `LOG_LEVEL` | Log level (DEBUG/INFO/WARNING/ERROR) | INFO |
| `API_V1_PREFIX` | API version prefix | /api/v1 |

Future placeholders (not used yet):
- `RAZORPAY_KEY_ID`
- `RAZORPAY_KEY_SECRET`
- `LLM_API_KEY`

## Test Commands

### Backend

```bash
cd backend
pytest -v           # Run all tests
ruff check .        # Lint
```

### Frontend

```bash
cd frontend
npm run lint        # ESLint
npx tsc --noEmit    # Type check
npm run build       # Production build
```

## Development Commands

```bash
# Full stack
docker compose up -d                          # Start PostgreSQL
cd backend && uvicorn app.main:app --reload   # Start backend
cd frontend && npm run dev                    # Start frontend

# Database migrations
cd backend
alembic revision --autogenerate -m "description"  # Create migration
alembic upgrade head                               # Apply migrations
```

## Security

- Never commit `.env` files
- Never use real payment credentials
- Razorpay integration uses Test Mode only
- The LLM must NEVER directly authorize or execute a payment

## License

Internal hackathon project — not for distribution.
