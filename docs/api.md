# Transaction Twin — API Documentation

## Base URL

```
http://localhost:8000
```

## Versioning

All business APIs are versioned under `/api/v1/`.

Infrastructure endpoints (like `/health`) are unversioned.

## Endpoints

### Health

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/health` | Liveness check (no DB) | None |
| GET | `/api/v1/health` | Readiness check (with DB) | None |

### Health Response

```json
{
  "status": "ok"
}
```

### Readiness Response

```json
{
  "status": "ok",
  "database": true
}
```

## Error Format

All errors follow a consistent format:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable description"
  }
}
```

### Error Codes

| Code | Status | Description |
|------|--------|-------------|
| `NOT_FOUND` | 404 | Resource not found |
| `VALIDATION_ERROR` | 422 | Input validation failed |
| `UNAUTHORIZED` | 401 | Authentication required |
| `RATE_LIMIT_EXCEEDED` | 429 | Too many requests |
| `INTERNAL_SERVER_ERROR` | 500 | Unexpected server error |

## Interactive Docs

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
