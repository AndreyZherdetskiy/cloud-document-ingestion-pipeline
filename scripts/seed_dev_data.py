#!/usr/bin/env python3
"""Idempotent local/dev seed — tenant acme + S3 fixtures + SQS check."""

from __future__ import annotations

import asyncio

from doc_pipeline.config.settings import get_settings
from doc_pipeline.infrastructure.aws.s3 import get_s3_client
from doc_pipeline.infrastructure.aws.sqs import get_sqs_client
from doc_pipeline.infrastructure.db.session import get_async_sessionmaker
from doc_pipeline.seed.dev import seed_dev


async def _run() -> None:
    settings = get_settings()
    sessionmaker = get_async_sessionmaker(settings)
    s3 = get_s3_client(settings)
    sqs = get_sqs_client(settings)
    async with sessionmaker() as session:
        report = await seed_dev(session, s3, settings, sqs=sqs)
    print(
        f"seed_dev done: slug={report.tenant_slug} "
        f"tenants_created={report.tenants_created} "
        f"documents_created={report.documents_created} "
        f"s3_objects_created={report.s3_objects_created} "
        f"queues_ok={report.queues_ok}"
    )


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
