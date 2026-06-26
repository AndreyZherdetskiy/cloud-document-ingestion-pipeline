#!/usr/bin/env python3
"""Generate dev RSA keypair — writes gitignored PEM files and patches repo .env."""

from __future__ import annotations

import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _REPO_ROOT / ".env"
_JWT_DIR = _REPO_ROOT / ".local" / "jwt"
_PRIVATE_PATH = _JWT_DIR / "private.pem"
_PUBLIC_PATH = _JWT_DIR / "public.pem"


def _generate_rsa_pem_pair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


def _pem_to_env_value(pem: str) -> str:
    return pem.strip().replace("\n", "\\n")


def _patch_env(updates: dict[str, str]) -> None:
    raw = _ENV_PATH.read_text(encoding="utf-8")
    lines = raw.splitlines()
    keys_done: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in line:
            key = line.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}")
                keys_done.add(key)
                continue
        new_lines.append(line)
    for key, value in updates.items():
        if key not in keys_done:
            new_lines.append(f"{key}={value}")
    _ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def main() -> None:
    if not _ENV_PATH.is_file():
        print("error: .env missing — copy .env.example to .env first", file=sys.stderr)
        raise SystemExit(1)

    private_pem, public_pem = _generate_rsa_pem_pair()
    _JWT_DIR.mkdir(parents=True, exist_ok=True)
    _PRIVATE_PATH.write_text(private_pem, encoding="utf-8")
    _PUBLIC_PATH.write_text(public_pem, encoding="utf-8")

    _patch_env(
        {
            "JWT_PUBLIC_KEY_PEM": _pem_to_env_value(public_pem),
            "JWT_PRIVATE_KEY_PEM": _pem_to_env_value(private_pem),
            "JWT_PUBLIC_KEY_PATH": str(_PUBLIC_PATH.relative_to(_REPO_ROOT)),
            "JWT_PRIVATE_KEY_PATH": str(_PRIVATE_PATH.relative_to(_REPO_ROOT)),
            "JWT_PUBLIC_KEY_FILE": str(_PUBLIC_PATH.relative_to(_REPO_ROOT)),
        }
    )
    print(
        f"dev JWT keys written to {_JWT_DIR.relative_to(_REPO_ROOT)}/ "
        f"and {_ENV_PATH.name} updated (PEM values not printed)"
    )


if __name__ == "__main__":
    main()
