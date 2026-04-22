"""Unit tests for live_ingest_demo S3 PUT URL resolution."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"


def _load_scripts_module(module_name: str):
    module_path = _SCRIPTS_DIR / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_load_scripts_module("mint_dev_jwt")
_live_ingest_demo = _load_scripts_module("live_ingest_demo")
_resolve_s3_put_url = _live_ingest_demo._resolve_s3_put_url

_LOCALSTACK_URL = "http://localstack:4566/bucket/key?X-Amz-Signature=abc"


@pytest.mark.parametrize(
    ("env", "expected_url", "expected_host"),
    [
        ({}, "http://127.0.0.1:4566/bucket/key?X-Amz-Signature=abc", "localstack:4566"),
        ({"LIVE_DEMO_IN_NETWORK": "1"}, _LOCALSTACK_URL, None),
        ({"S3_PUT_REWRITE_LOCALSTACK": "0"}, _LOCALSTACK_URL, None),
    ],
)
def test_resolve_s3_put_url_localstack_rewrite(
    monkeypatch: pytest.MonkeyPatch,
    env: dict[str, str],
    expected_url: str,
    expected_host: str | None,
) -> None:
    for key in ("LIVE_DEMO_IN_NETWORK", "S3_PUT_REWRITE_LOCALSTACK"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    put_url, host_override = _resolve_s3_put_url(_LOCALSTACK_URL)

    assert put_url == expected_url
    assert host_override == expected_host
