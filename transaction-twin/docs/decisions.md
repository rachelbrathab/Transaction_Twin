# Architectural Decisions — Transaction Twin

## Decision Log

Record of significant architectural decisions and their reasoning.

---

### AD-001: Modular Monolith over Microservices

**Date:** Sprint 1  
**Status:** Accepted  
**Context:** Need to choose the deployment architecture for a hackathon project.  
**Decision:** Use a modular monolith with clear internal layer separation (API → Services → Database).  
**Rationale:**
- Hackathon timeline demands simplicity
- Single deployment reduces operational complexity
- Internal module boundaries allow future extraction to services
- FastAPI supports clean layer separation without microservice overhead  
**Consequences:** Easier development and deployment; may need refactoring if the team scales significantly.

---

### AD-002: PostgreSQL over SQLite

**Date:** Sprint 1  
**Status:** Accepted  
**Context:** Need a database for development and production.  
**Decision:** PostgreSQL as the primary database, SQLite only in isolated unit tests.  
**Rationale:**
- PostgreSQL supports JSON columns, full-text search, and advanced querying needed for risk data
- Behavioral compatibility between dev and prod is critical for a fintech system
- PostgreSQL is required by the hackathon spec
- Docker Compose makes local PostgreSQL trivial  
**Consequences:** Requires Docker for local development; PostgreSQL-specific features (like JSONB) are available.

---

### AD-003: Async SQLAlchemy with asyncpg

**Date:** Sprint 1  
**Status:** Accepted  
**Context:** Need to choose ORM and database driver.  
**Decision:** SQLAlchemy 2.x with asyncpg driver for async PostgreSQL access.  
**Rationale:**
- SQLAlchemy 2.x has mature async support
- asyncpg is the fastest async PostgreSQL driver
- FastAPI works naturally with async/await
- Future LLM calls will benefit from non-blocking I/O  
**Consequences:** All database operations must be awaited; Alembic env configured for async migrations.

---

### AD-004: LLM Isolation from Payment Decisions

**Date:** Sprint 1  
**Status:** Accepted  
**Context:** The system uses AI for intent interpretation and explanation, but payments must be deterministic.  
**Decision:** Strictly separate LLM calls from payment authorization logic.  
**Rationale:**
- LLMs are non-deterministic and cannot guarantee safety
- Financial regulations require auditable, deterministic decision paths
- Risk signals should be validated before influencing decisions
- This separation is a hard architectural constraint, not a guideline  
**Consequences:** The LLM can only produce structured data (intents, explanations). All decision logic uses deterministic policies and validated ML signals.

---

### AD-005: Environment-Based Configuration

**Date:** Sprint 1  
**Status:** Accepted  
**Context:** Need to manage configuration across environments.  
**Decision:** pydantic-settings for backend, `.env` files for local development, never commit secrets.  
**Rationale:**
- Type-safe configuration with validation at startup
- Clear separation of concerns (dev/test/prod)
- Standard pattern for Python web applications
- `.env.example` documents all available settings  
**Consequences:** All config changes require env var updates; no hardcoded values in source code.

---

### AD-006: Structured Logging with structlog

**Date:** Sprint 1  
**Status:** Accepted  
**Context:** Need logging that supports debugging and eventually supports trace IDs.  
**Decision:** structlog for structured, machine-readable logs.  
**Rationale:**
- Structured logs enable log aggregation and search
- Supports context variables for request tracing
- Clean console output in development, JSON in production
- Lightweight, no heavy dependencies  
**Consequences:** All log calls use key-value pairs; no free-text log messages.

---

### AD-007: Component Library Over External UI Framework

**Date:** Sprint 1  
**Status:** Accepted  
**Context:** Need a design system for the frontend.  
**Decision:** Build simple, custom React components with Tailwind CSS rather than using shadcn/ui or MUI.  
**Rationale:**
- Full control over the design language
- No dependency on third-party component libraries
- Tailwind CSS is already in the stack
- Keeps the bundle small
- Custom components can be evolved to match the fintech aesthetic  
**Consequences:** More initial work; but complete design control for the premium fintech command center look.
