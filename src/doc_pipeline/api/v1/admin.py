"""Platform admin operations — DLQ replay."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends

from doc_pipeline.api.deps import (
    PLATFORM_ADMIN_ROLES,
    Principal,
    get_current_principal,
    get_dlq_service,
    require_roles,
)
from doc_pipeline.domain.schemas.admin import DlqReplayRequest, DlqReplayResponse
from doc_pipeline.domain.services.dlq_service import DlqService

router = APIRouter(tags=["admin"])

_PROBLEM_401 = {"description": "Missing or invalid JWT"}
_PROBLEM_403 = {"description": "Authenticated but role not permitted (Platform Admin required)"}
_PROBLEM_422 = {"description": "Request validation failed"}

_REPLAY_EXAMPLES = {
    "two_messages": {
        "summary": "Redrive two DLQ messages",
        "description": "Platform Admin starts a message move from DLQ to the main queue.",
        "value": {"message_ids": ["msg-1", "msg-2"]},
    },
}


@router.post(
    "/admin/dlq/replay",
    response_model=DlqReplayResponse,
    summary="Replay DLQ messages",
    description=(
        "Platform Admin only. Accepts SQS message IDs from the DLQ and starts a "
        "redrive (message move) to the main ingestion queue. API clients receive 403."
    ),
    responses={
        200: {"description": "Redrive accepted"},
        401: _PROBLEM_401,
        403: _PROBLEM_403,
        422: _PROBLEM_422,
    },
)
async def replay_dlq(
    body: Annotated[DlqReplayRequest, Body(openapi_examples=_REPLAY_EXAMPLES)],
    principal: Annotated[Principal, Depends(get_current_principal)],
    service: Annotated[DlqService, Depends(get_dlq_service)],
) -> DlqReplayResponse:
    require_roles(principal, PLATFORM_ADMIN_ROLES)
    replayed = await service.replay(body.message_ids)
    return DlqReplayResponse(replayed_count=len(replayed), message_ids=replayed)
