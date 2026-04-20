from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from doc_pipeline.api.deps import get_db_session
from doc_pipeline.domain.errors import DependencyUnavailableError

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    summary="Liveness probe",
    description="Returns 200 when the process is up. Does not check dependencies.",
)
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get(
    "/ready",
    summary="Readiness probe",
    description=(
        "Returns 200 when PostgreSQL accepts connections. "
        "Fails with 503 when the database is unreachable."
    ),
    responses={
        503: {"description": "PostgreSQL unavailable"},
    },
)
async def ready(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, str]:
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        raise DependencyUnavailableError("PostgreSQL is unavailable") from exc
    return {"status": "ready"}
