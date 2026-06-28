"""DLQ redrive against LocalStack — skipped when Docker ports are blocked.

Poison policy / replay procedure: docs/runbooks/dlq-replay.md (full prose Task 14).
"""

from __future__ import annotations

import contextlib
import json
import time
import urllib.error
import urllib.request

import boto3
import pytest

from doc_pipeline.config.settings import get_settings


def _localstack_reachable() -> bool:
    settings = get_settings()
    endpoint = (settings.aws_endpoint_url or "http://localhost:4566").rstrip("/")
    try:
        urllib.request.urlopen(f"{endpoint}/_localstack/health", timeout=1)  # noqa: S310
        return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


@pytest.mark.integration
def test_poison_message_redrives_to_dlq() -> None:
    if not _localstack_reachable():
        pytest.skip("LocalStack/Docker not reachable — deselected from make ci by default")

    settings = get_settings()
    endpoint = settings.aws_endpoint_url or "http://localhost:4566"
    region = settings.aws_region
    sqs = boto3.client(
        "sqs",
        endpoint_url=endpoint,
        region_name=region,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )

    # Ephemeral queues so Compose init queues stay untouched.
    suffix = str(int(time.time() * 1000))
    dlq_url = sqs.create_queue(QueueName=f"it-poison-dlq-{suffix}")["QueueUrl"]
    dlq_arn = sqs.get_queue_attributes(
        QueueUrl=dlq_url,
        AttributeNames=["QueueArn"],
    )["Attributes"]["QueueArn"]
    redrive = json.dumps({"deadLetterTargetArn": dlq_arn, "maxReceiveCount": 5})
    main_url = sqs.create_queue(
        QueueName=f"it-poison-main-{suffix}",
        Attributes={
            "VisibilityTimeout": "1",
            "RedrivePolicy": redrive,
        },
    )["QueueUrl"]
    try:
        sqs.send_message(QueueUrl=main_url, MessageBody="integration-poison")
        # LocalStack 4.14 redrives on the receive *after* maxReceiveCount is hit.
        # Expire visibility immediately so five receive cycles stay fast.
        for _ in range(5):
            resp = sqs.receive_message(
                QueueUrl=main_url,
                MaxNumberOfMessages=1,
                VisibilityTimeout=1,
                WaitTimeSeconds=1,
            )
            assert resp.get("Messages"), "expected message on main queue before redrive"
            receipt = resp["Messages"][0]["ReceiptHandle"]
            sqs.change_message_visibility(
                QueueUrl=main_url,
                ReceiptHandle=receipt,
                VisibilityTimeout=0,
            )

        # Sixth receive on main triggers redrive; main may already be empty.
        sqs.receive_message(
            QueueUrl=main_url,
            MaxNumberOfMessages=1,
            VisibilityTimeout=1,
            WaitTimeSeconds=1,
        )

        deadline = time.time() + 10
        dlq_has_message = False
        while time.time() < deadline:
            dlq_depth = int(
                sqs.get_queue_attributes(
                    QueueUrl=dlq_url,
                    AttributeNames=["ApproximateNumberOfMessages"],
                )["Attributes"]["ApproximateNumberOfMessages"]
            )
            if dlq_depth >= 1:
                dlq_has_message = True
                break
            dlq_resp = sqs.receive_message(
                QueueUrl=dlq_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=1,
            )
            if dlq_resp.get("Messages"):
                dlq_has_message = True
                break
            time.sleep(0.25)

        if not dlq_has_message:
            pytest.fail(
                "LocalStack did not move the poison message to the DLQ after the "
                "sixth receive (maxReceiveCount=5); moto unit test covers AWS "
                "RedrivePolicy semantics"
            )
    finally:
        for url in (main_url, dlq_url):
            with contextlib.suppress(Exception):
                sqs.delete_queue(QueueUrl=url)
