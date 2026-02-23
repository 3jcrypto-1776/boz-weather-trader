"""Boz Weather Trader backend package."""

from __future__ import annotations

from pathlib import Path


def _read_version() -> str:
    """Read version from the root VERSION file (single source of truth)."""
    # VERSION file lives at project root, two levels up from backend/
    version_file = Path(__file__).resolve().parent.parent / "VERSION"
    try:
        return version_file.read_text().strip()
    except FileNotFoundError:
        return "0.0.0-dev"


__version__: str = _read_version()
