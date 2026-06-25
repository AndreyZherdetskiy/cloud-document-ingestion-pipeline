"""``python -m doc_pipeline.worker.ingestion_main`` entrypoint."""

from __future__ import annotations

import asyncio

from doc_pipeline.worker.ingestion_consumer import run_ingestion_worker


def main() -> None:
    asyncio.run(run_ingestion_worker())


if __name__ == "__main__":
    main()
