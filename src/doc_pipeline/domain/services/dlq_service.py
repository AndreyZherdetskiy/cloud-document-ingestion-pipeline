"""DLQ replay orchestration — wraps SQS redrive; fake for unit tests."""

from __future__ import annotations

from typing import Protocol

from botocore.client import BaseClient

from doc_pipeline.config.settings import Settings
from doc_pipeline.infrastructure.aws.sqs import start_dlq_redrive


class DlqService(Protocol):
    async def replay(self, message_ids: list[str]) -> list[str]: ...


class FakeDlqService:
    """Unit-test double — records requested message IDs, no AWS."""

    def __init__(self) -> None:
        self.replayed: list[str] = []

    async def replay(self, message_ids: list[str]) -> list[str]:
        self.replayed.extend(message_ids)
        return list(message_ids)


class SqsDlqService:
    def __init__(self, client: BaseClient, settings: Settings) -> None:
        self._client = client
        self._settings = settings

    async def replay(self, message_ids: list[str]) -> list[str]:
        # Stage 1: start a queue-level redrive; message_ids are accepted for the
        # admin contract and echoed back (selective move is Stage 2).
        start_dlq_redrive(
            self._client,
            source_queue_url=self._settings.sqs_dlq_url,
            destination_queue_url=self._settings.sqs_queue_url,
        )
        return list(message_ids)
