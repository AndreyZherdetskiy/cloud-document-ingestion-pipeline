"""Worker observability: INFO logs and OTel spans on message handling."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from doc_pipeline.config.settings import Settings
from doc_pipeline.worker import ingestion_consumer
from doc_pipeline.worker.ingestion_consumer import run_once

S3_TEST_EVENT = {
    "Service": "Amazon S3",
    "Event": "s3:TestEvent",
    "Time": "2026-04-16T08:00:00.000Z",
    "Bucket": "dev-doc-pipeline",
    "RequestId": "req-1",
    "HostId": "host-1",
}


@pytest.fixture
def span_exporter() -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    yield exporter
    provider.shutdown()


@pytest.mark.asyncio
async def test_ingestion_test_event_still_deletes_message(
    span_exporter: InMemorySpanExporter,
) -> None:
    with mock_aws():
        ingestion_consumer._stop.clear()
        sqs = boto3.client("sqs", region_name="eu-central-1")
        queue_url = sqs.create_queue(QueueName="test-ingest-obs-testevent")["QueueUrl"]
        sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(S3_TEST_EVENT))
        settings = Settings(sqs_queue_url=queue_url, otel_sdk_disabled=False)
        factory = MagicMock()

        await run_once(
            sqs=sqs,
            session_factory=factory,
            settings=settings,
        )

        attrs = sqs.get_queue_attributes(
            QueueUrl=queue_url,
            AttributeNames=["ApproximateNumberOfMessages"],
        )
        assert int(attrs["Attributes"]["ApproximateNumberOfMessages"]) == 0

        spans = span_exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "ingest.handle_message"
        assert spans[0].attributes.get("messaging.system") == "aws.sqs"
        assert spans[0].attributes.get("ignored") == "test_event"


@pytest.mark.asyncio
async def test_ingestion_test_event_logs_acked(span_exporter: InMemorySpanExporter) -> None:
    with mock_aws():
        ingestion_consumer._stop.clear()
        sqs = boto3.client("sqs", region_name="eu-central-1")
        queue_url = sqs.create_queue(QueueName="test-ingest-obs-log")["QueueUrl"]
        sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(S3_TEST_EVENT))
        settings = Settings(sqs_queue_url=queue_url, otel_sdk_disabled=False)

        with patch("doc_pipeline.worker.ingestion_consumer.logger") as log_mock:
            await run_once(
                sqs=sqs,
                session_factory=MagicMock(),
                settings=settings,
            )
            log_mock.info.assert_called_once_with("ingestion_test_event_acked")
