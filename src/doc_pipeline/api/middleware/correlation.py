"""UUIDv7 correlation ID middleware."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from opentelemetry import trace
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from doc_pipeline.api.errors import problem_response
from doc_pipeline.domain.ids import generate_uuidv7
from doc_pipeline.logging import bind_correlation_id, clear_correlation_id

CORRELATION_RESPONSE_HEADER = "X-Correlation-ID"


def _read_correlation_header(request: Request) -> str | None:
    return request.headers.get("X-Correlation-ID") or request.headers.get("X-Correlation-Id")


def resolve_correlation_id(raw: str | None) -> str | None:
    if raw is None or raw.strip() == "":
        return str(generate_uuidv7())
    try:
        parsed = uuid.UUID(raw)
    except ValueError:
        return None
    if parsed.version != 7:
        return None
    return str(parsed)


class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        raw = _read_correlation_header(request)
        if raw is not None and raw.strip() != "":
            resolved = resolve_correlation_id(raw)
            if resolved is None:
                return problem_response(
                    status=422,
                    title="Unprocessable Entity",
                    detail="X-Correlation-ID must be a UUID version 7",
                )
        else:
            resolved = str(generate_uuidv7())

        token = bind_correlation_id(resolved)
        try:
            response = await call_next(request)
            span = trace.get_current_span()
            if span.is_recording():
                span.set_attribute("correlation_id", resolved)
        finally:
            clear_correlation_id(token)

        response.headers[CORRELATION_RESPONSE_HEADER] = resolved
        return response
