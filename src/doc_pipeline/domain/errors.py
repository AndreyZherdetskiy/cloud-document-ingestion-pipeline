from doc_pipeline.domain.enums import DocumentStatus


class InvalidTransitionError(Exception):
    def __init__(self, from_status: DocumentStatus, to_status: DocumentStatus) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"Invalid transition: {from_status} -> {to_status}")


class UnauthorizedError(Exception):
    """Missing or invalid JWT → 401 Problem Details."""

    def __init__(self, detail: str = "Missing or invalid Authorization Bearer JWT") -> None:
        self.detail = detail
        super().__init__(detail)


class ForbiddenError(Exception):
    """Authenticated but lacking required role → 403 Problem Details."""

    def __init__(self, detail: str = "Insufficient permissions") -> None:
        self.detail = detail
        super().__init__(detail)


class NotFoundError(Exception):
    """Resource not found in tenant scope → 404 (never 403 for foreign IDs)."""

    def __init__(self, detail: str = "Not found") -> None:
        self.detail = detail
        super().__init__(detail)


class ConflictError(Exception):
    """Idempotency payload mismatch or other conflict → 409."""

    def __init__(self, detail: str = "Conflict") -> None:
        self.detail = detail
        super().__init__(detail)


class RateLimitExceededError(Exception):
    """Redis rate-limit bucket exhausted → 429."""

    def __init__(self, detail: str = "Rate limit exceeded") -> None:
        self.detail = detail
        super().__init__(detail)


class ValidationError(Exception):
    """Business-rule validation failure → 400."""

    def __init__(self, detail: str = "Validation failed") -> None:
        self.detail = detail
        super().__init__(detail)


class DependencyUnavailableError(Exception):
    """Readiness dependency down → 503."""

    def __init__(self, detail: str = "Dependency unavailable") -> None:
        self.detail = detail
        super().__init__(detail)
