from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.responses import RedirectResponse

from doc_pipeline.api.errors import register_exception_handlers
from doc_pipeline.api.middleware.correlation import CorrelationMiddleware
from doc_pipeline.api.router import api_router
from doc_pipeline.config.settings import get_settings
from doc_pipeline.logging import configure_logging
from doc_pipeline.observability.otel import configure_otel, instrument_fastapi, shutdown_otel

OPENAPI_TAGS = [
    {"name": "documents", "description": "Document metadata create/list/get."},
    {
        "name": "uploads",
        "description": "Presigned S3 upload URLs (files never stream through the API).",
    },
    {"name": "jobs", "description": "Processing jobs, retry, and cancel."},
    {"name": "audit", "description": "Append-only audit timeline for a document."},
    {"name": "admin", "description": "Platform admin operations such as DLQ replay."},
    {"name": "health", "description": "Liveness and readiness probes."},
]


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings)
    configure_otel(settings.otel_service_name, settings)
    yield
    shutdown_otel()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        lifespan=_lifespan,
        title="Cloud Document Ingestion Pipeline",
        summary="Control-plane API for document ingestion; binary objects go to S3 via presign.",
        description=(
            "## Control vs data plane\n\n"
            "This API manages metadata, jobs, and audit. **Files never stream through the API.** "
            "Clients obtain a **presigned PUT** URL and upload directly to S3.\n\n"
            "## Auth and headers\n\n"
            "- **JWT** Bearer (RS256) identifies the tenant and role.\n"
            "- **Idempotency-Key** on `POST /v1/documents`.\n"
            "- **X-Correlation-ID** must be a UUIDv7 when supplied; "
            "the server generates one if missing.\n"
            "- Errors use **RFC 7807** Problem Details (`application/problem+json`).\n"
            "- Cross-tenant IDs return **404**, not 403.\n\n"
            "## Outbound webhooks\n\n"
            "Clients may receive signed outbound webhooks (`document.processed` / "
            "`document.failed`) with header `X-Webhook-Signature` (HMAC-SHA256).\n"
        ),
        openapi_tags=OPENAPI_TAGS,
        docs_url="/v1/docs",
        redoc_url="/v1/redoc",
        openapi_url="/v1/openapi.json",
        servers=[{"url": "http://localhost:8000", "description": "Local Compose"}],
    )

    app.add_middleware(CorrelationMiddleware)
    register_exception_handlers(app)
    app.include_router(api_router, prefix="/v1")
    instrument_fastapi(app, settings)

    @app.get("/docs", include_in_schema=False)
    @app.get("/docs/", include_in_schema=False)
    async def redirect_docs() -> RedirectResponse:
        return RedirectResponse(url="/v1/docs", status_code=307)

    @app.get("/redoc", include_in_schema=False)
    @app.get("/redoc/", include_in_schema=False)
    async def redirect_redoc() -> RedirectResponse:
        return RedirectResponse(url="/v1/redoc", status_code=307)

    return app
