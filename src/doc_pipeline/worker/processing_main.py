"""``python -m doc_pipeline.worker.processing_main`` entrypoint."""

from __future__ import annotations

import asyncio

from doc_pipeline.worker.processing_consumer import run_processing_worker


def main() -> None:
    asyncio.run(run_processing_worker())


if __name__ == "__main__":
    main()
