"""SQS helpers — DLQ redrive wrapper (LocalStack / AWS compatible)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import boto3
from botocore.client import BaseClient

if TYPE_CHECKING:
    from doc_pipeline.config.settings import Settings


def get_sqs_client(settings: Settings) -> BaseClient:
    kwargs: dict[str, Any] = {
        "region_name": settings.aws_region,
        "aws_access_key_id": settings.aws_access_key_id,
        "aws_secret_access_key": settings.aws_secret_access_key,
    }
    if settings.aws_endpoint_url:
        kwargs["endpoint_url"] = settings.aws_endpoint_url
    return boto3.client("sqs", **kwargs)


def start_dlq_redrive(
    client: BaseClient,
    *,
    source_queue_url: str,
    destination_queue_url: str,
) -> str:
    """Start a message move task from DLQ to the main queue.

    Uses ``start_message_move_task`` (SQS redrive API). LocalStack supports this
    for Stage 1 demos; AWS requires appropriate IAM on both queues.
    """
    response = client.start_message_move_task(
        SourceArn=_queue_url_to_arn(source_queue_url),
        DestinationArn=_queue_url_to_arn(destination_queue_url),
    )
    return str(response.get("TaskHandle", ""))


def _queue_url_to_arn(queue_url: str) -> str:
    """Best-effort ARN from a LocalStack/AWS queue URL for redrive APIs."""
    # http://localhost:4566/000000000000/dev-document-ingestion-dlq
    # https://sqs.eu-central-1.amazonaws.com/000000000000/name
    parts = queue_url.rstrip("/").split("/")
    account = parts[-2] if len(parts) >= 2 else "000000000000"
    name = parts[-1]
    region = "eu-central-1"
    if "sqs." in queue_url and ".amazonaws.com" in queue_url:
        host = queue_url.split("//", 1)[-1].split("/", 1)[0]
        region = host.split(".")[1]
    return f"arn:aws:sqs:{region}:{account}:{name}"
