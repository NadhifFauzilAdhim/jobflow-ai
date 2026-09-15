"""Tests for authentication, session tokens, and public deployment security."""

import pytest
from httpx import AsyncClient, ASGITransport
from jobflow.api.app import app
from jobflow.config import settings
from jobflow.core.security import create_session_token, verify_session_token, verify_credentials
from jobflow.db.database import init_db


@pytest.mark.asyncio
async def test_security_core_functions():
    """Test cryptographic token creation and verification."""
    token = create_session_token("admin", expires_hours=1)
    assert token is not None
    assert "." in token

    username = verify_session_token(token)
    assert username == "admin"

    # Tampered token
    tampered = token[:-5] + "aaaaa"
    assert verify_session_token(tampered) is None

    # Invalid token format
    assert verify_session_token("invalid_token") is None

    # Credentials verification
    assert verify_credentials("admin", settings.AUTH_PASSWORD) is True
    assert verify_credentials("admin", "wrong_password") is False
    assert verify_credentials("unknown", settings.AUTH_PASSWORD) is False


@pytest.mark.asyncio
async def test_public_health_and_login_page():
    """Verify health check and login page are always publicly accessible."""
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:8000") as ac:
        # Health check must never require authentication
        res_health = await ac.get("/health")
        assert res_health.status_code == 200
        assert res_health.json() == {"status": "healthy", "service": "jobflow-ai"}

        # Login page is public
        res_login = await ac.get("/login")
        assert res_login.status_code == 200
        assert "Sign In" in res_login.text or "Protected Portal" in res_login.text


@pytest.mark.asyncio
async def test_unauthenticated_access_restrictions():
    """Verify unauthenticated requests are properly redirected or blocked."""
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:8000", follow_redirects=False) as ac:
        # Dashboard should redirect to /login
        res_dash = await ac.get("/")
        assert res_dash.status_code == 303
        assert "/login" in res_dash.headers["location"]

        # API routes should return 401 Unauthorized
        res_api_jobs = await ac.get("/api/jobs")
        assert res_api_jobs.status_code == 401
        assert "Authentication required" in res_api_jobs.json()["detail"]

        res_api_prof = await ac.get("/api/profile/status")
        assert res_api_prof.status_code == 401


@pytest.mark.asyncio
async def test_login_flow_and_authenticated_session():
    """Verify login authentication, cookie issuance, and subsequent authenticated access."""
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:8000", follow_redirects=False) as ac:
        # 1. Invalid login attempt
        bad_login = await ac.post("/api/auth/login", json={
            "username": "admin",
            "password": "wrong_password_123"
        })
        assert bad_login.status_code == 401

        # 2. Valid login attempt
        good_login = await ac.post("/api/auth/login", json={
            "username": settings.AUTH_USERNAME,
            "password": settings.AUTH_PASSWORD,
            "remember_me": True
        })
        assert good_login.status_code == 200
        login_data = good_login.json()
        assert login_data["status"] == "ok"
        token = login_data["token"]
        assert token is not None

        # Verify cookie was set
        assert settings.SESSION_COOKIE_NAME in good_login.cookies

        # 3. Access dashboard with established session cookie
        res_dash = await ac.get("/")
        assert res_dash.status_code == 200
        assert "JobFlow AI" in res_dash.text

        # 4. Access API with established session cookie
        res_jobs = await ac.get("/api/jobs")
        assert res_jobs.status_code == 200

        # 5. Check /api/auth/me
        res_me = await ac.get("/api/auth/me")
        assert res_me.status_code == 200
        assert res_me.json()["authenticated"] is True
        assert res_me.json()["username"] == settings.AUTH_USERNAME

        # 6. Logout
        res_logout = await ac.post("/api/auth/logout")
        assert res_logout.status_code == 200

        # 7. Access API after logout should now fail
        res_jobs_after = await ac.get("/api/jobs")
        assert res_jobs_after.status_code == 401


@pytest.mark.asyncio
async def test_bearer_token_authorization():
    """Verify programmatic API access using Bearer token authorization header."""
    await init_db()
    valid_token = create_session_token("admin", expires_hours=2)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:8000") as ac:
        headers = {"Authorization": f"Bearer {valid_token}"}
        res = await ac.get("/api/jobs", headers=headers)
        assert res.status_code == 200

        res_me = await ac.get("/api/auth/me", headers=headers)
        assert res_me.status_code == 200
        assert res_me.json()["authenticated"] is True
