# Architecture — Transaction Twin

## System Architecture

### Current State (Sprint 1)

```
┌──────────────────────────────────────────────┐
│                Frontend                       │
│  Next.js + TypeScript + Tailwind CSS          │
│  ├── App Shell (Sidebar + Header)             │
│  ├── Design System Components                 │
│  └── API Client Configuration                 │
└──────────────────┬───────────────────────────┘
                   │ HTTP REST
                   ▼
┌──────────────────────────────────────────────┐
│                REST API                       │
│  FastAPI + Pydantic v2                        │
│  ├── /health (liveness)                       │
│  ├── /api/v1/health (readiness)               │
│  ├── Versioned routes (/api/v1/*)             │
│  ├── Structured error responses               │
│  └── Structured logging (structlog)           │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│              Database Layer                   │
│  SQLAlchemy 2.x + Alembic                     │
│  ├── Async engine + session management        │
│  ├── Dependency injection (get_db)            │
│  └── PostgreSQL 16 (Docker Compose)           │
└──────────────────────────────────────────────┘
```

### Future State (Sprint 2+)

```
                    ┌──────────────────┐
                    │    Frontend      │
                    │  Developer API   │
                    │  Consumer UI     │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │   REST API       │
                    │  /api/v1/*       │
                    └────────┬─────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
┌──────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ Intent       │  │ Transaction Twin │  │ Risk Engine      │
│ Engine       │  │                  │  │                  │
│ ─ NL parse   │  │ ─ Intent drift   │  │ ─ ML scoring     │
│ ─ Extraction │  │ ─ State tracking │  │ ─ Behavioral     │
│ ─ LLM calls  │  │ ─ Deviation      │  │ ─ Agent rep.     │
└──────┬───────┘  └────────┬─────────┘  └────────┬─────────┘
       │                   │                     │
       └───────────────────┼─────────────────────┘
                           │
                  ┌────────▼─────────┐
                  │  Policy Engine   │
                  │  Deterministic   │
                  │  ALLOW / REVIEW  │
                  │  STEP-UP / BLOCK │
                  └────────┬─────────┘
                           │
                  ┌────────▼─────────┐
                  │  Decision Layer  │
                  │  Audit trail     │
                  │  Explanations    │
                  └────────┬─────────┘
                           │
                  ┌────────▼─────────┐
                  │  Razorpay        │
                  │  Test Mode       │
                  │  Integration     │
                  └──────────────────┘
```

## Key Architectural Decisions

### 1. LLM Must Never Authorize Payments

```
SAFE:     LLM → Interpretation → Structured Data → Policy + ML → Decision
UNSAFE:   LLM → "BLOCK/ALLOW" → Payment
```

The architecture enforces this separation. LLMs are used only for
interpretation and explanation. All payment decisions pass through
deterministic policies and validated risk signals.

### 2. Modular Monolith

For a hackathon, a single deployable unit with clear internal separation
is simpler and faster than microservices. We can extract services later
if scaling requires it.

### 3. API Versioning

All business APIs live under `/api/v1/`. The root `/health` is unversioned
for infrastructure checks. This allows version evolution without breaking
clients.

### 4. Async-First Backend

FastAPI with async SQLAlchemy enables high concurrency without blocking
the event loop. This is critical for an AI-heavy workload where we'll
make many concurrent LLM API calls in future sprints.

### 5. Deterministic Safety Layer

The Policy Engine (future) must be the final authority on payment decisions.
It uses only deterministic rules — never probabilistic ML outputs — as the
ultimate gate before any payment execution.
