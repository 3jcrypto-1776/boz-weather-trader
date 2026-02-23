"""Version info endpoint — current version + update-check via GitHub Releases.

Also provides self-update endpoints that proxy to the updater sidecar container.
"""

from __future__ import annotations

import contextlib
import json

import httpx
from fastapi import APIRouter, Depends

from backend import __version__
from backend.api.deps import get_current_user
from backend.api.response_schemas import UpdateStatus, UpdateTriggerResponse, VersionInfo
from backend.common.config import get_settings
from backend.common.logging import get_logger
from backend.common.models import User

router = APIRouter()
logger = get_logger("SYSTEM")

_GITHUB_REPO = "aclarkson2013/boz-weather-trader"
_GITHUB_API_URL = f"https://api.github.com/repos/{_GITHUB_REPO}/releases/latest"
_CACHE_KEY = "boz:latest_version"
_CACHE_TTL_SECONDS = 3600  # 1 hour


def _parse_semver(version: str) -> tuple[int, ...]:
    """Parse 'X.Y.Z' into a comparable tuple. Strips leading 'v'."""
    cleaned = version.lstrip("v").split("-")[0]  # strip pre-release
    parts = cleaned.split(".")
    return tuple(int(p) for p in parts if p.isdigit())


async def _get_redis():
    """Get async Redis client, returns None if unavailable."""
    try:
        import redis.asyncio as aioredis

        settings = get_settings()
        return aioredis.from_url(settings.redis_url)
    except Exception:
        return None


async def _check_latest_version() -> tuple[str | None, str | None]:
    """Check GitHub Releases API for the latest version.

    Returns (latest_version_tag, release_url) or (None, None) on failure.
    Uses Redis cache with 1-hour TTL to avoid GitHub rate limits.
    """
    # Try cache first
    r = await _get_redis()
    if r:
        try:
            cached = await r.get(_CACHE_KEY)
            if cached:
                data = json.loads(cached)
                await r.aclose()
                return data.get("tag"), data.get("url")
        except Exception:
            pass  # Cache miss or error — fall through to API

    # Fetch from GitHub
    tag_name = None
    html_url = None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                _GITHUB_API_URL,
                headers={"Accept": "application/vnd.github.v3+json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                tag_name = data.get("tag_name")
                html_url = data.get("html_url")

                # Cache the result
                if r and tag_name:
                    try:
                        cache_data = json.dumps({"tag": tag_name, "url": html_url})
                        await r.setex(_CACHE_KEY, _CACHE_TTL_SECONDS, cache_data)
                    except Exception:
                        pass  # Non-critical
    except Exception as exc:
        logger.debug(f"GitHub version check failed: {exc}")

    if r:
        with contextlib.suppress(Exception):
            await r.aclose()

    return tag_name, html_url


@router.get("", response_model=VersionInfo)
async def get_version() -> VersionInfo:
    """Return current version and check if an update is available."""
    latest_tag, release_url = await _check_latest_version()

    update_available = False
    latest_version = None

    if latest_tag:
        latest_version = latest_tag.lstrip("v")
        try:
            current_parts = _parse_semver(__version__)
            latest_parts = _parse_semver(latest_tag)
            update_available = latest_parts > current_parts
        except (ValueError, IndexError):
            update_available = False

    return VersionInfo(
        current_version=__version__,
        latest_version=latest_version,
        update_available=update_available,
        release_url=release_url,
    )


@router.post("/update", response_model=UpdateTriggerResponse, status_code=202)
async def trigger_update(
    _user: User = Depends(get_current_user),
) -> UpdateTriggerResponse:
    """Trigger a self-update via the updater sidecar container.

    Sends a POST to the updater sidecar which runs git pull, docker compose build,
    and docker compose up -d. Requires authentication.
    """
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{settings.updater_url}/update",
                headers={"Authorization": f"Bearer {settings.updater_secret}"},
            )
            data = resp.json()
            if resp.status_code == 202:
                return UpdateTriggerResponse(status="started", message=data.get("message", ""))
            if resp.status_code == 409:
                return UpdateTriggerResponse(
                    status="already_running", message="Update already in progress"
                )
            return UpdateTriggerResponse(status="error", message=data.get("error", "Unknown error"))
    except httpx.ConnectError:
        logger.warning("Updater sidecar unreachable at %s", settings.updater_url)
        return UpdateTriggerResponse(
            status="unavailable",
            message="Updater sidecar not running. Is the updater container started?",
        )
    except Exception as exc:
        logger.error("Failed to contact updater sidecar: %s", exc)
        return UpdateTriggerResponse(status="error", message=str(exc))


@router.get("/update/status", response_model=UpdateStatus)
async def get_update_status(
    _user: User = Depends(get_current_user),
) -> UpdateStatus:
    """Get the current status of an in-progress self-update.

    Proxies the status request to the updater sidecar container.
    Requires authentication.
    """
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{settings.updater_url}/status",
                headers={"Authorization": f"Bearer {settings.updater_secret}"},
            )
            if resp.status_code == 200:
                data = resp.json()
                return UpdateStatus(
                    status=data.get("status", "idle"),
                    step=data.get("step"),
                    error=data.get("error"),
                    started_at=data.get("started_at"),
                )
    except httpx.ConnectError:
        pass  # Sidecar not running — return idle
    except Exception as exc:
        logger.debug("Failed to get update status: %s", exc)

    return UpdateStatus(status="idle")
