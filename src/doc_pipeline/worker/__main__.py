"""``python -m doc_pipeline.worker`` entrypoint (legacy — use split workers)."""

from __future__ import annotations

_OPERATOR_MESSAGE = (
    "doc_pipeline.worker is retired. Start a split worker instead: "
    "python -m doc_pipeline.worker.ingestion_main | "
    "python -m doc_pipeline.worker.processing_main | "
    "python -m doc_pipeline.worker.stuck_main"
)


def main() -> None:
    raise SystemExit(_OPERATOR_MESSAGE)


if __name__ == "__main__":
    main()
