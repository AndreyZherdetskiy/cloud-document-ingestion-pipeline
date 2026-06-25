"""Asyncio periodic stuck-job scanner and QUEUED document recovery (spec §3.4, §8.2)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from doc_pipeline.config.settings import Settings
from doc_pipeline.domain.enums import DocumentStatus, DocumentType, JobStatus, JobType
from doc_pipeline.domain.ids import generate_uuidv7
from doc_pipeline.domain.models.document import Document
from doc_pipeline.domain.models.job import Job
from doc_pipeline.worker.events import ProcessDocumentMessage, serialize_process_document_message

logger = structlog.get_logger(__name__)

_NON_TERMINAL_JOB_STATUSES = frozenset({JobStatus.PENDING, JobStatus.RUNNING})


async def mark_stuck_jobs(
    *,
    session: AsyncSession,
    older_than: timedelta,
    now: datetime | None = None,
) -> int:
    """Mark RUNNING/PENDING jobs with started_at older than threshold as STUCK."""
    ts = now or datetime.now(UTC)
    cutoff = ts - older_than
    result = await session.execute(
        select(Job).where(
            Job.status.in_(_NON_TERMINAL_JOB_STATUSES),
            Job.started_at.is_not(None),
            Job.started_at < cutoff,
        )
    )
    jobs = list(result.scalars())
    for job in jobs:
        job.status = JobStatus.STUCK
    if jobs:
        await session.commit()
    return len(jobs)


async def reenqueue_stale_queued_documents(
    *,
    session: AsyncSession,
    settings: Settings,
    sqs_client: Any,
    older_than: timedelta,
    now: datetime | None = None,
) -> int:
    """Re-enqueue PROCESS_DOCUMENT for QUEUED documents older than threshold.

    Recovers the Task 0 failure mode: DB committed QUEUED but SQS send_message failed.
    Processing worker duplicate delivery is safe (Redis NX + terminal short-circuit).
    """
    ts = now or datetime.now(UTC)
    cutoff = ts - older_than
    result = await session.execute(
        select(Document).where(
            Document.status == DocumentStatus.QUEUED,
            Document.updated_at < cutoff,
        )
    )
    docs = list(result.scalars())
    sent = 0
    for doc in docs:
        job_result = await session.execute(
            select(Job)
            .where(
                Job.document_id == doc.id,
                Job.job_type == JobType.PROCESSING.value,
                Job.status.in_(_NON_TERMINAL_JOB_STATUSES),
            )
            .order_by(Job.created_at.desc())
            .limit(1)
        )
        job = job_result.scalar_one_or_none()
        if job is None:
            continue
        msg = ProcessDocumentMessage(
            schema_version="1",
            message_type="PROCESS_DOCUMENT",
            job_id=job.id,
            document_id=doc.id,
            tenant_id=doc.tenant_id,
            document_type=DocumentType(doc.document_type),
            s3_bucket=doc.s3_bucket or "",
            s3_key=doc.s3_key or "",
            attempt=job.attempt,
            correlation_id=generate_uuidv7(),
            requested_hooks=("virus", "ocr", "extract"),
        )
        sqs_client.send_message(
            QueueUrl=settings.sqs_processing_queue_url,
            MessageBody=serialize_process_document_message(msg),
        )
        sent += 1
    return sent


async def run_stuck_scanner_loop(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    stop_event: asyncio.Event,
    sqs_client: Any | None = None,
) -> None:
    """Sleep ``stuck_scan_interval_seconds`` between mark-stuck and QUEUED recovery scans."""
    older_than = timedelta(seconds=settings.stuck_job_older_than_seconds)
    interval = settings.stuck_scan_interval_seconds
    while not stop_event.is_set():
        async with sessionmaker() as session:
            stuck_count = await mark_stuck_jobs(session=session, older_than=older_than)
            reenqueued_count = 0
            if sqs_client is not None:
                reenqueued_count = await reenqueue_stale_queued_documents(
                    session=session,
                    settings=settings,
                    sqs_client=sqs_client,
                    older_than=older_than,
                )
        logger.info(
            "stuck_scan_cycle",
            stuck_jobs=stuck_count,
            reenqueued=reenqueued_count,
        )
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except TimeoutError:
            continue
