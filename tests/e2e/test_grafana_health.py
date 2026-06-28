"""Live Grafana boot check — skipped when :3000 is down."""

from __future__ import annotations

import json
import urllib.request

import pytest

pytestmark = pytest.mark.e2e


def test_grafana_api_health_returns_ok(grafana_health_url: str) -> None:
    with urllib.request.urlopen(grafana_health_url, timeout=5) as response:  # noqa: S310
        assert response.status == 200
        payload = json.loads(response.read().decode("utf-8"))
    assert payload.get("database") == "ok"
