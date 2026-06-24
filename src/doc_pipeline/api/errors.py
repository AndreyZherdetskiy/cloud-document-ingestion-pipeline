"""RFC 7807 Problem Details helpers and exception handlers."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from doc_pipeline.domain.errors import (
    ConflictError,
    DependencyUnavailableError,
    ForbiddenError,
    InvalidTransitionError,
    NotFoundError,
    RateLimitExceededError,
    UnauthorizedError,
    ValidationError,
)


def problem_response(
    status: int,
    title: str,
    detail: str,
    type_: str = "about:blank",
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={
            "type": type_,
            "title": title,
            "status": status,
            "detail": detail,
        },
    )


def _format_validation_detail(exc: RequestValidationError) -> str:
    parts: list[str] = []
    for error in exc.errors():
        loc = ".".join(str(part) for part in error.get("loc", ()))
        msg = error.get("msg", "invalid value")
        parts.append(f"{loc}: {msg}" if loc else str(msg))
    return "; ".join(parts) if parts else "Request validation failed"


async def invalid_transition_handler(
    _request: Request,
    exc: InvalidTransitionError,
) -> JSONResponse:
    return problem_response(
        status=409,
        title="Conflict",
        detail=str(exc),
    )


async def validation_exception_handler(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return problem_response(
        status=422,
        title="Unprocessable Entity",
        detail=_format_validation_detail(exc),
    )


async def unauthorized_handler(_request: Request, exc: UnauthorizedError) -> JSONResponse:
    return problem_response(status=401, title="Unauthorized", detail=exc.detail)


async def forbidden_handler(_request: Request, exc: ForbiddenError) -> JSONResponse:
    return problem_response(status=403, title="Forbidden", detail=exc.detail)


async def not_found_handler(_request: Request, exc: NotFoundError) -> JSONResponse:
    return problem_response(status=404, title="Not Found", detail=exc.detail)


async def conflict_handler(_request: Request, exc: ConflictError) -> JSONResponse:
    return problem_response(status=409, title="Conflict", detail=exc.detail)


async def rate_limit_handler(_request: Request, exc: RateLimitExceededError) -> JSONResponse:
    return problem_response(status=429, title="Too Many Requests", detail=exc.detail)


async def validation_handler(_request: Request, exc: ValidationError) -> JSONResponse:
    return problem_response(status=400, title="Bad Request", detail=exc.detail)


async def dependency_unavailable_handler(
    _request: Request,
    exc: DependencyUnavailableError,
) -> JSONResponse:
    return problem_response(status=503, title="Service Unavailable", detail=exc.detail)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(InvalidTransitionError, invalid_transition_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(UnauthorizedError, unauthorized_handler)  # type: ignore[arg-type]
    app.add_exception_handler(ForbiddenError, forbidden_handler)  # type: ignore[arg-type]
    app.add_exception_handler(NotFoundError, not_found_handler)  # type: ignore[arg-type]
    app.add_exception_handler(ConflictError, conflict_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RateLimitExceededError, rate_limit_handler)  # type: ignore[arg-type]
    app.add_exception_handler(ValidationError, validation_handler)  # type: ignore[arg-type]
    app.add_exception_handler(DependencyUnavailableError, dependency_unavailable_handler)  # type: ignore[arg-type]
