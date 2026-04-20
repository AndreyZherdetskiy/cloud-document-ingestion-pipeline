"""Legacy ``python -m doc_pipeline.worker`` must not start the monolithic consumer."""

from __future__ import annotations

import pytest

from doc_pipeline.worker.__main__ import main


def test_worker_main_exits_with_operator_message() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main()
    msg = str(exc_info.value)
    assert "ingestion_main" in msg
    assert "processing_main" in msg
    assert "stuck_main" in msg
