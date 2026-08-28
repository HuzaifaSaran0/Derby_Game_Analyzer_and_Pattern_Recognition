"""Web login and password change."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from game_analyzer.store import GameStore
from game_analyzer.web import create_app
from game_analyzer.web.auth import DEFAULT_PASSWORD, DEFAULT_USERNAME


@pytest.fixture
def auth_client(tmp_path: Path) -> TestClient:
    store = GameStore(tmp_path / "games.sqlite", root=tmp_path)
    auth_path = tmp_path / "web_auth.json"
    secret_path = tmp_path / "session_secret"
    app = create_app(
        store,
        auth_enabled=True,
        auth_path=auth_path,
        session_secret_path=secret_path,
    )
    return TestClient(app)


def test_unauthenticated_redirects_to_login(auth_client: TestClient):
    response = auth_client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"].startswith("/login?next=")


def test_login_page_loads(auth_client: TestClient):
    response = auth_client.get("/login")
    assert response.status_code == 200
    assert "Sign in" in response.text
    assert "Web-only account" not in response.text
    assert "First-time default" not in response.text


def test_login_success(auth_client: TestClient):
    response = auth_client.post(
        "/login",
        data={"username": DEFAULT_USERNAME, "password": DEFAULT_PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/"
    home = auth_client.get("/")
    assert home.status_code == 200
    assert "Card table" in home.text


def test_login_failure(auth_client: TestClient):
    response = auth_client.post(
        "/login",
        data={"username": DEFAULT_USERNAME, "password": "wrong"},
    )
    assert response.status_code == 401
    assert "Invalid username or password" in response.text


def test_api_requires_login(auth_client: TestClient):
    response = auth_client.get("/api/stats")
    assert response.status_code == 401
    assert response.json()["detail"] == "Unauthorized"


def test_change_password(auth_client: TestClient, tmp_path: Path):
    auth_path = tmp_path / "web_auth.json"
    auth_client.post(
        "/login",
        data={"username": DEFAULT_USERNAME, "password": DEFAULT_PASSWORD},
    )
    page = auth_client.get("/change-password")
    assert page.status_code == 200
    assert "Change password" in page.text

    bad = auth_client.post(
        "/change-password",
        data={
            "current_password": "wrong",
            "new_password": "newpass",
            "confirm_password": "newpass",
        },
    )
    assert bad.status_code == 400
    assert "Current password is incorrect" in bad.text

    ok = auth_client.post(
        "/change-password",
        data={
            "current_password": DEFAULT_PASSWORD,
            "new_password": "newpass",
            "confirm_password": "newpass",
            "new_username": "operator",
        },
    )
    assert ok.status_code == 200
    assert "Password updated" in ok.text

    import json

    record = json.loads(auth_path.read_text(encoding="utf-8"))
    assert record["username"] == "operator"

    auth_client.post("/logout")
    denied = auth_client.post(
        "/login",
        data={"username": DEFAULT_USERNAME, "password": DEFAULT_PASSWORD},
    )
    assert denied.status_code == 401

    allowed = auth_client.post(
        "/login",
        data={"username": "operator", "password": "newpass"},
        follow_redirects=False,
    )
    assert allowed.status_code == 302


def test_logout(auth_client: TestClient):
    auth_client.post(
        "/login",
        data={"username": DEFAULT_USERNAME, "password": DEFAULT_PASSWORD},
    )
    response = auth_client.post("/logout", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"
    assert auth_client.get("/history", follow_redirects=False).status_code == 302
