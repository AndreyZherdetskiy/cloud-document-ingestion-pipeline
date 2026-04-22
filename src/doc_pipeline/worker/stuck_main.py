"""``python -m doc_pipeline.worker.stuck_main`` — asyncio stuck-job scanner entrypoint."""

from __future__ import annotations

import asyncio
import signal

from doc_pipeline.config.settings import Settings, get_settings
from doc_pipeline.infrastructure.aws.sqs import get_sqs_client
from doc_pipeline.infrastructure.db.session import get_async_sessionmaker
from doc_pipeline.logging import configure_logging
from doc_pipeline.observability.otel import configure_otel, shutdown_otel
from doc_pipeline.worker.stuck_scanner import run_stuck_scanner_loop

_stop = asyncio.Event()


def _request_stop(*_args: object) -> None:
    _stop.set()


async def run_stuck_scanner(settings: Settings | None = None) -> None:
    cfg = settings or get_settings()
    configure_logging(cfg)
    configure_otel("doc-pipeline-stuck-scanner", cfg)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            signal.signal(sig, _request_stop)

    session_factory = get_async_sessionmaker(cfg)
    sqs = get_sqs_client(cfg)
    try:
        await run_stuck_scanner_loop(
            sessionmaker=session_factory,
            settings=cfg,
            stop_event=_stop,
            sqs_client=sqs,
        )
    finally:
        shutdown_otel()


def main() -> None:
    asyncio.run(run_stuck_scanner())


if __name__ == "__main__":
    main()
