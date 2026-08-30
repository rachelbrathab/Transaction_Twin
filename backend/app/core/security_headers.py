"""Security headers middleware for production deployment.

Adds standard security headers to all HTTP responses.
Designed to work behind a reverse proxy (Caddy/nginx) which may
also set these headers. Application-level headers serve as defense-in-depth.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses.

    Headers:
        - X-Content-Type-Options: nosniff
        - X-Frame-Options: DENY
        - Referrer-Policy: strict-origin-when-cross-origin
        - X-XSS-Protection: 0 (modern best practice — rely on CSP instead)
        - Strict-Transport-Security: max-age=63072000 (only in production)
        - Content-Security-Policy: basic policy for SPA
    """

    def __init__(self, app, is_production: bool = False):  # noqa: ANN001
        super().__init__(app)
        self.is_production = is_production

    async def dispatch(self, request: Request, call_next) -> Response:  # noqa: ANN002
        response: Response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "0"

        if self.is_production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains; preload"
            )
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; "
                "font-src 'self'; "
                "connect-src 'self'; "
                "frame-ancestors 'none'"
            )
        else:
            # Relaxed CSP for development (allows hot reload etc.)
            response.headers["Content-Security-Policy"] = (
                "default-src 'self' 'unsafe-inline' 'unsafe-eval'"
            )

        return response
