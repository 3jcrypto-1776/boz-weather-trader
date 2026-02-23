"""Tests for the /api/version endpoint.

Verifies current version reporting and GitHub-based update checking.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from backend import __version__
from backend.main import app


@pytest.fixture
async def bare_client() -> AsyncClient:
    """Client with no dependency overrides — tests /api/version directly."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


_FAKE_REQUEST = httpx.Request("GET", "https://api.github.com/repos/test/test/releases/latest")


def _make_github_response(tag_name: str = "v1.1.0", status_code: int = 200):
    """Build a mock GitHub API response."""
    data = {
        "tag_name": tag_name,
        "html_url": f"https://github.com/test/test/releases/tag/{tag_name}",
    }
    return httpx.Response(status_code=status_code, json=data, request=_FAKE_REQUEST)


def _make_github_error_response():
    """Build a 404 / error GitHub API response."""
    return httpx.Response(status_code=404, json={"message": "Not Found"}, request=_FAKE_REQUEST)


class TestVersionEndpoint:
    """Tests for GET /api/version."""

    @pytest.mark.asyncio
    async def test_returns_current_version(self, bare_client: AsyncClient):
        """The endpoint should always return the current app version."""
        with (
            patch("backend.api.version._get_redis", return_value=None),
            patch("backend.api.version.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_make_github_error_response())
            mock_client_cls.return_value = mock_client

            resp = await bare_client.get("/api/version")

        assert resp.status_code == 200
        body = resp.json()
        assert body["current_version"] == __version__

    @pytest.mark.asyncio
    async def test_update_available_when_newer_version(self, bare_client: AsyncClient):
        """Should report update_available=True when GitHub has a newer version."""
        with (
            patch("backend.api.version._get_redis", return_value=None),
            patch("backend.api.version.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_make_github_response("v99.0.0"))
            mock_client_cls.return_value = mock_client

            resp = await bare_client.get("/api/version")

        body = resp.json()
        assert body["update_available"] is True
        assert body["latest_version"] == "99.0.0"
        assert body["release_url"] is not None

    @pytest.mark.asyncio
    async def test_no_update_when_same_version(self, bare_client: AsyncClient):
        """Should report update_available=False when versions match."""
        with (
            patch("backend.api.version._get_redis", return_value=None),
            patch("backend.api.version.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_make_github_response(f"v{__version__}"))
            mock_client_cls.return_value = mock_client

            resp = await bare_client.get("/api/version")

        body = resp.json()
        assert body["update_available"] is False

    @pytest.mark.asyncio
    async def test_no_update_when_older_version(self, bare_client: AsyncClient):
        """Should report update_available=False when GitHub has older version."""
        with (
            patch("backend.api.version._get_redis", return_value=None),
            patch("backend.api.version.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_make_github_response("v0.0.1"))
            mock_client_cls.return_value = mock_client

            resp = await bare_client.get("/api/version")

        body = resp.json()
        assert body["update_available"] is False

    @pytest.mark.asyncio
    async def test_graceful_on_github_failure(self, bare_client: AsyncClient):
        """Should return version info even when GitHub API fails."""
        with (
            patch("backend.api.version._get_redis", return_value=None),
            patch("backend.api.version.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_make_github_error_response())
            mock_client_cls.return_value = mock_client

            resp = await bare_client.get("/api/version")

        body = resp.json()
        assert body["current_version"] == __version__
        assert body["latest_version"] is None
        assert body["update_available"] is False

    @pytest.mark.asyncio
    async def test_graceful_on_network_error(self, bare_client: AsyncClient):
        """Should handle network exceptions gracefully."""
        with (
            patch("backend.api.version._get_redis", return_value=None),
            patch("backend.api.version.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            mock_client_cls.return_value = mock_client

            resp = await bare_client.get("/api/version")

        body = resp.json()
        assert body["current_version"] == __version__
        assert body["update_available"] is False

    @pytest.mark.asyncio
    async def test_redis_cache_hit(self, bare_client: AsyncClient):
        """Should use cached version from Redis when available."""
        cached_data = json.dumps(
            {
                "tag": "v99.0.0",
                "url": "https://github.com/test/test/releases/tag/v99.0.0",
            }
        )
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=cached_data)
        mock_redis.aclose = AsyncMock()

        with patch("backend.api.version._get_redis", return_value=mock_redis):
            resp = await bare_client.get("/api/version")

        body = resp.json()
        assert body["update_available"] is True
        assert body["latest_version"] == "99.0.0"
        mock_redis.get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_redis_cache_miss_then_fetch(self, bare_client: AsyncClient):
        """Should fetch from GitHub when Redis cache misses."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()
        mock_redis.aclose = AsyncMock()

        with (
            patch("backend.api.version._get_redis", return_value=mock_redis),
            patch("backend.api.version.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_make_github_response("v99.0.0"))
            mock_client_cls.return_value = mock_client

            resp = await bare_client.get("/api/version")

        body = resp.json()
        assert body["latest_version"] == "99.0.0"
        mock_redis.setex.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_auth_required(self, bare_client: AsyncClient):
        """Version endpoint should not require authentication."""
        with (
            patch("backend.api.version._get_redis", return_value=None),
            patch("backend.api.version.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_make_github_error_response())
            mock_client_cls.return_value = mock_client

            resp = await bare_client.get("/api/version")

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_response_schema(self, bare_client: AsyncClient):
        """Response should contain all expected fields."""
        with (
            patch("backend.api.version._get_redis", return_value=None),
            patch("backend.api.version.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_make_github_response("v2.0.0"))
            mock_client_cls.return_value = mock_client

            resp = await bare_client.get("/api/version")

        body = resp.json()
        assert "current_version" in body
        assert "latest_version" in body
        assert "update_available" in body
        assert "release_url" in body
