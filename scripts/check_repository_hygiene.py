#!/usr/bin/env python3
"""Reject tracked runtime artifacts and high-signal credentials."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAX_SCAN_BYTES = 1_000_000
ALLOWED_ENV_FILES = {".env.example"}
FORBIDDEN_SUFFIXES = {".db", ".key", ".log", ".pem", ".sqlite", ".sqlite3"}
FORBIDDEN_NAMES = {"frontend/.env.production"}
SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?im)^(?:SECRET_KEY|SYSTEM_EMAIL_PASSWORD|DEFAULT_ADMIN_PASSWORD|DEFAULT_USER_PASSWORD|"
    r"ENCRYPTION_KEY|TRAFFIC_READ_TOKEN)[ \t]*=[ \t]*(?P<value>[^\r\n]*)[ \t]*$"
)
PRIVATE_KEY_PATTERN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
COOKIE_PATTERN = re.compile(r"(?i)\bceac_session\s*=")
PLACEHOLDER_MARKERS = (
    "<",
    "change-this-",
    "example",
    "placeholder",
    "replace-me",
    "your-",
)


def trackedFiles() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [ROOT / name for name in result.stdout.split("\0") if name]


def isForbiddenPath(path: Path) -> bool:
    relative = path.relative_to(ROOT).as_posix()
    if relative in FORBIDDEN_NAMES:
        return True
    if path.name.startswith(".env") and path.name not in ALLOWED_ENV_FILES:
        return True
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        return True
    return path.name.lower().startswith("cookies") and path.suffix.lower() == ".json"


def looksLikePlaceholder(value: str) -> bool:
    normalized = value.strip().strip("\"'").lower()
    return not normalized or any(marker in normalized for marker in PLACEHOLDER_MARKERS)


def scanText(path: Path) -> list[str]:
    if path.stat().st_size > MAX_SCAN_BYTES:
        return []
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    findings = []
    if PRIVATE_KEY_PATTERN.search(content):
        findings.append("contains a private key")
    if COOKIE_PATTERN.search(content):
        findings.append("contains a CEACStatusBot session cookie")
    for match in SECRET_ASSIGNMENT_PATTERN.finditer(content):
        if not looksLikePlaceholder(match.group("value")):
            findings.append(f"contains a non-placeholder {match.group(0).split('=', 1)[0]} assignment")
    return findings


def main() -> int:
    failures = []
    for path in trackedFiles():
        if not path.exists():
            continue
        relative = path.relative_to(ROOT).as_posix()
        if isForbiddenPath(path):
            failures.append(f"{relative}: runtime or secret file must not be tracked")
            continue
        for finding in scanText(path):
            failures.append(f"{relative}: {finding}")
    if failures:
        print("Repository hygiene check failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("Repository hygiene check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
