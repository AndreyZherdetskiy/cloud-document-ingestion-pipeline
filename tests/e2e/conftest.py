"""E2E fixtures — require doc-pipeline API on localhost (see `make stack-up`)."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import urllib.error
import urllib.request
from pathlib import Path
from types import ModuleType

import httpx
import pytest

from doc_pipeline.config.settings import get_settings

REPO_ROOT = Path(__file__).resolve().parents[2]
API_BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
HEALTH_URL = f"{API_BASE}/v1/health"
POLL_TIMEOUT_SECONDS = 180.0
POLL_INTERVAL_SECONDS = 2.0


def _load_script_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        msg = f"cannot load script module from {path}"
        raise ImportError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_mint_dev_jwt = _load_script_module("mint_dev_jwt", REPO_ROOT / "scripts" / "mint_dev_jwt.py")
mint_jwt = _mint_dev_jwt.mint_jwt
lookup_tenant_id = _mint_dev_jwt.lookup_tenant_id
DEFAULT_ROLES = _mint_dev_jwt.DEFAULT_ROLES


def _url_returns_200(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:  # noqa: S310
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _require_live_api() -> None:
    if not _url_returns_200(HEALTH_URL):
        pytest.skip(
            f"API not healthy at {HEALTH_URL} — start compose (`make stack-up`) for optional e2e"
        )


def _require_jwt_private_key() -> str:
    private_pem = get_settings().jwt_private_key_pem.strip()
    if not private_pem:
        pytest.skip(
            "JWT_PRIVATE_KEY_PEM is empty — run `make gen-dev-jwt` and recreate api for e2e"
        )
    return private_pem


@pytest.fixture(scope="session")
def api_base_url() -> str:
    _require_live_api()
    return API_BASE


@pytest.fixture(scope="session")
def auth_token_acme(api_base_url: str) -> str:
    del api_base_url
    private_pem = _require_jwt_private_key()
    settings = get_settings()
    tenant_id = asyncio.run(lookup_tenant_id("acme"))
    return mint_jwt(
        private_pem=private_pem,
        tenant_id=tenant_id,
        roles=DEFAULT_ROLES,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        sub="e2e-acme",
    )


@pytest.fixture(scope="session")
def http_client() -> httpx.Client:
    with httpx.Client(timeout=30.0) as client:
        yield client
