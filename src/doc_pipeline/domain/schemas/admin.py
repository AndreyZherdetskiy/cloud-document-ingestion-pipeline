"""Pydantic schemas for platform admin operations."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DlqReplayRequest(BaseModel):
    message_ids: list[str] = Field(
        description="SQS message IDs in the DLQ to redrive to the main queue.",
        min_length=1,
        examples=[["msg-1", "msg-2"]],
    )


class DlqReplayResponse(BaseModel):
    replayed_count: int = Field(description="Number of message IDs accepted for redrive.")
    message_ids: list[str] = Field(description="Echo of message IDs submitted for replay.")
