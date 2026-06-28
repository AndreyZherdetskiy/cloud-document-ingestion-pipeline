"""Perf docs relative-link contract tests."""

import re
from pathlib import Path

PERF_README = Path("docs/perf/README.md")
K6_README = Path("scripts/k6/README.md")

_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _k6_readme_link_target(readme_text: str) -> str:
    for label, target in _MARKDOWN_LINK.findall(readme_text):
        if "scripts/k6/README.md" in label or target.endswith("scripts/k6/README.md"):
            return target
    raise AssertionError(f"{PERF_README} must contain a markdown link to scripts/k6/README.md")


def test_perf_readme_k6_link_resolves_to_scripts_k6_readme() -> None:
    rel = _k6_readme_link_target(PERF_README.read_text(encoding="utf-8"))
    resolved = (Path("docs/perf") / rel).resolve()
    expected = K6_README.resolve()
    assert (
        resolved == expected
    ), f"{PERF_README} link {rel!r} resolves to {resolved}, expected {expected}"
