"""Pydantic schemas for jobs list/get/retry/cancel."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from doc_pipeline.domain.enums import JobStatus, JobType


class JobResponse(BaseModel):
    id: uuid.UUID = Field(description="Job UUIDv7 primary key.")
    document_id: uuid.UUID = Field(description="Parent document UUIDv7.")
    job_type: JobType = Field(description="Job type (INGESTION, PROCESSING).")
    status: JobStatus = Field(description="Current job status.")
    attempt: int = Field(description="Current attempt number (starts at 1).")
    max_attempts: int = Field(description="Maximum attempts before permanent failure.")
    error_code: str | None = Field(default=None, description="Machine-readable error when failed.")
    error_message: str | None = Field(default=None, description="Human-readable error when failed.")
    created_at: datetime = Field(description="When the job row was created (UTC).")
    started_at: datetime | None = Field(default=None, description="When the worker started.")
    finished_at: datetime | None = Field(
        default=None,
        description="When the job reached a terminal status.",
    )


class JobListResponse(BaseModel):
    items: list[JobResponse] = Field(description="Page of jobs for the caller tenant.")
    next_cursor: str | None = Field(
        default=None,
        description="Opaque cursor for the next page; null when no more items.",
    )
    limit: int = Field(description="Page size applied to this response.")
