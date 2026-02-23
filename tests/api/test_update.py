"""Tests for the self-update endpoints (POST /api/version/update, GET /api/version/update/status).

Verifies the backend correctly proxies to the updater sidecar container.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app

_FAKE_REQUEST = httpx.Request("POST", "http://updater:9999/update")


@pytest.fixture
def mock_db_user():
    """Mock get_current_user to return a fake user."""
    user = AsyncMock()
    user.id = 1
    user.kalshi_key_id = "test"
    return user


@pytest.fixture
async def authed_client(mock_db_user) -> AsyncClient:
    """Client with auth dependency overridden."""
    from backend.api.deps import get_current_user

    app.dependency_overrides[get_current_user] = lambda: mock_db_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
async def unauthed_client() -> AsyncClient:
    """Client that simulates no user (auth fails with 401)."""
    from fastapi import HTTPException

    from backend.api.deps import get_current_user

    async def _no_user():
        raise HTTPException(status_code=401, detail="Not authenticated")

    app.dependency_overrides[get_current_user] = _no_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


class TestTriggerUpdate:
    """Tests for POST /api/version/update."""

    @pytest.mark.asyncio
    async def test_trigger_update_success(self, authed_client: AsyncClient):
        """Should return 202 when updater sidecar accepts the request."""
        mock_resp = httpx.Response(
            202,
            json={"status": "started", "message": "Update process initiated"},
            request=_FAKE_REQUEST,
        )
        with patch("backend.api.version.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_client

            resp = await authed_client.post("/api/version/update")

        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "started"

    @pytest.mark.asyncio
    async def test_trigger_update_already_running(self, authed_client: AsyncClient):
        """Should return 202 with already_running when update is in progress."""
        mock_resp = httpx.Response(
            409,
            json={"error": "Update already in progress"},
            request=_FAKE_REQUEST,
        )
        with patch("backend.api.version.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_client

            resp = await authed_client.post("/api/version/update")

        body = resp.json()
        assert body["status"] == "already_running"

    @pytest.mark.asyncio
    async def test_trigger_update_sidecar_unreachable(self, authed_client: AsyncClient):
        """Should return 202 with unavailable status when sidecar is down."""
        with patch("backend.api.version.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            mock_cls.return_value = mock_client

            resp = await authed_client.post("/api/version/update")

        body = resp.json()
        assert body["status"] == "unavailable"
        assert "not running" in body["message"].lower() or "sidecar" in body["message"].lower()

    @pytest.mark.asyncio
    async def test_trigger_update_requires_auth(self, unauthed_client: AsyncClient):
        """Should return 401 when not authenticated."""
        resp = await unauthed_client.post("/api/version/update")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_trigger_sends_shared_secret(self, authed_client: AsyncClient):
        """Should send the UPDATER_SECRET in the Authorization header."""
        mock_resp = httpx.Response(
            202,
            json={"status": "started", "message": "Update process initiated"},
            request=_FAKE_REQUEST,
        )
        with (
            patch("backend.api.version.httpx.AsyncClient") as mock_cls,
            patch("backend.api.version.get_settings") as mock_settings,
        ):
            settings = mock_settings.return_value
            settings.updater_url = "http://updater:9999"
            settings.updater_secret = "test-secret-123"

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_client

            await authed_client.post("/api/version/update")

        # Verify the Authorization header was sent with the correct secret
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer test-secret-123"


class TestUpdateStatus:
    """Tests for GET /api/version/update/status."""

    @pytest.mark.asyncio
    async def test_get_status_idle(self, authed_client: AsyncClient):
        """Should return idle when no update is in progress."""
        mock_resp = httpx.Response(
            200,
            json={"status": "idle", "step": None, "error": None, "started_at": None},
            request=httpx.Request("GET", "http://updater:9999/status"),
        )
        with patch("backend.api.version.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_client

            resp = await authed_client.get("/api/version/update/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "idle"

    @pytest.mark.asyncio
    async def test_get_status_in_progress(self, authed_client: AsyncClient):
        """Should return building status when update is in progress."""
        mock_resp = httpx.Response(
            200,
            json={
                "status": "building",
                "step": "docker compose build",
                "error": None,
                "started_at": "2026-02-23T12:00:00Z",
            },
            request=httpx.Request("GET", "http://updater:9999/status"),
        )
        with patch("backend.api.version.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_client

            resp = await authed_client.get("/api/version/update/status")

        body = resp.json()
        assert body["status"] == "building"
        assert body["step"] == "docker compose build"

    @pytest.mark.asyncio
    async def test_get_status_sidecar_unreachable(self, authed_client: AsyncClient):
        """Should return idle when sidecar is unreachable."""
        with patch("backend.api.version.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            mock_cls.return_value = mock_client

            resp = await authed_client.get("/api/version/update/status")

        body = resp.json()
        assert body["status"] == "idle"

    @pytest.mark.asyncio
    async def test_get_status_requires_auth(self, unauthed_client: AsyncClient):
        """Should return 401 when not authenticated."""
        resp = await unauthed_client.get("/api/version/update/status")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_status_response_schema(self, authed_client: AsyncClient):
        """Response should contain all expected fields."""
        mock_resp = httpx.Response(
            200,
            json={
                "status": "done",
                "step": "complete",
                "error": None,
                "started_at": "2026-02-23T12:00:00Z",
            },
            request=httpx.Request("GET", "http://updater:9999/status"),
        )
        with patch("backend.api.version.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_client

            resp = await authed_client.get("/api/version/update/status")

        body = resp.json()
        assert "status" in body
        assert "step" in body
        assert "error" in body
        assert "started_at" in body
