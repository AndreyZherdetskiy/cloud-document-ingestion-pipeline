"""Pin pre-commit: Ruff 0.8.x hook, no Docker, package in pyproject."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRE_COMMIT = ROOT / ".pre-commit-config.yaml"
PYPROJECT = ROOT / "pyproject.toml"


def test_ruff_pre_commit_rev_is_v0_8_6() -> None:
    text = PRE_COMMIT.read_text(encoding="utf-8")
    repo_marker = "repo: https://github.com/astral-sh/ruff-pre-commit"
    assert repo_marker in text
    ruff_block = text.split(repo_marker)[1].split("repo:")[0]
    assert "rev: v0.8.6" in ruff_block
    assert "      - id: ruff\n" in text.replace("\r\n", "\n")
    assert "      - id: ruff-format\n" in text.replace("\r\n", "\n")
    assert "id: ruff-check" not in text


def test_hooks_do_not_use_docker() -> None:
    text = PRE_COMMIT.read_text(encoding="utf-8")
    assert "docker" not in text.lower()


def test_pre_commit_hooks_include_detect_private_key() -> None:
    text = PRE_COMMIT.read_text(encoding="utf-8")
    assert "repo: https://github.com/pre-commit/pre-commit-hooks" in text
    assert "detect-private-key" in text


def test_pyproject_dev_group_includes_pre_commit() -> None:
    text = PYPROJECT.read_text(encoding="utf-8")
    assert "pre-commit>=4,<5" in text


def test_pre_commit_hooks_rev_is_v5_0_0() -> None:
    text = PRE_COMMIT.read_text(encoding="utf-8")
    repo_marker = "repo: https://github.com/pre-commit/pre-commit-hooks"
    assert repo_marker in text
    hooks_block = text.split(repo_marker)[1].split("repo:")[0]
    assert "rev: v5.0.0" in hooks_block


def test_makefile_hooks_installs_pre_commit() -> None:
    text = (ROOT / "Makefile").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert "\nhooks:\n\tuv run pre-commit install\n" in text
    assert "\nhooks-run:\n\tuv run pre-commit run --files " in text
    assert "docker" not in text.split("\nhooks-run:")[1].split("\n\n", 1)[0].lower()
