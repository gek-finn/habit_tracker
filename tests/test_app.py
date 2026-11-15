import re
import pytest
from werkzeug.security import check_password_hash
from habit_tracker import create_app
from habit_tracker.db import get_db, init_db

PASSWORD = "  a long password  "


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    app = create_app({"TESTING": True, "SECRET_KEY": "test-only", "DATABASE": str(tmp_path / "test.sqlite3")})
    with app.app_context():
        init_db()
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def token(client, path):
    response = client.get(path)
    return re.search(r'name="csrf_token" value="([^"]+)"', response.text)[1]


def register(client, username="Alice", **overrides):
    data = dict(username=username, password=PASSWORD, confirmation=PASSWORD, timezone="Europe/Kaliningrad")
    data.update(overrides)
    data["csrf_token"] = token(client, "/register")
    return client.post("/register", data=data)


def login(client, username="Alice", password=PASSWORD, next_path=""):
    path = "/login" + next_path
    return client.post(path, data={"username": username, "password": password, "csrf_token": token(client, path)})


def test_registration_hash_and_init_preserves_data(app, client):
    response = register(client)
    assert response.status_code == 302 and response.location == "/login"
    with app.app_context():
        init_db()
        row = get_db().execute("SELECT * FROM users").fetchone()
        assert row["username"] == "Alice"
        assert row["password_hash"] != PASSWORD
        assert check_password_hash(row["password_hash"], PASSWORD)
        assert not check_password_hash(row["password_hash"], PASSWORD.strip())
        assert row["timezone"] == "Europe/Kaliningrad"


def test_duplicate_case(app, client):
    register(client)
    response = register(client, "aLiCe")
    assert response.status_code == 400
    assert "уже занято" in response.text
    with app.app_context():
        assert get_db().execute("SELECT count(*) FROM users").fetchone()[0] == 1


def test_login_failure_success_logout(client):
    register(client)
    wrong = login(client, password="incorrect")
    absent = login(client, username="Absent", password="incorrect")
    assert wrong.status_code == absent.status_code == 400
    assert "Неверное имя пользователя или пароль" in wrong.text
    assert "Неверное имя пользователя или пароль" in absent.text
    response = login(client, username="ALICE")
    assert response.status_code == 302 and response.location == "/tracker"
    assert "Alice" in client.get("/tracker").text
    assert client.get("/logout").status_code == 405
    response = client.post("/logout", data={"csrf_token": token(client, "/tracker")})
    assert response.status_code == 302
    assert client.get("/tracker").status_code == 302


def test_private_page_and_isolation(app, client):
    assert client.get("/tracker").status_code == 302
    register(client)
    register(client, "Other_person", timezone="Asia/Tokyo")
    login(client)
    text = client.get("/tracker").text
    assert "Alice" in text and "Europe/Kaliningrad" in text
    assert "Other_person" not in text and "Asia/Tokyo" not in text
    other = app.test_client()
    login(other, username="Other_person")
    text = other.get("/tracker").text
    assert "Other_person" in text and "Alice" not in text


@pytest.mark.parametrize("path", ["/register", "/login", "/logout"])
def test_csrf_missing_and_invalid(client, path):
    register(client)
    login(client)
    assert client.post(path, data={}).status_code == 400
    assert client.post(path, data={"csrf_token": "invalid"}).status_code == 400
    assert client.get("/tracker").status_code == 200


@pytest.mark.parametrize("target", ["https://evil.example/", "//evil.example/", "/\\evil.example/", "https://localhost/tracker"])
def test_external_next_rejected(client, target):
    from urllib.parse import urlencode
    register(client)
    response = login(client, next_path="?" + urlencode({"next": target}))
    assert response.location == "/tracker"


def test_local_next(client):
    register(client)
    assert login(client, next_path="?next=/tracker?welcome=1").location == "/tracker?welcome=1"


def test_unknown_timezone(client):
    response = register(client, timezone="Mars/Olympus")
    assert response.status_code == 400
    assert "Выберите существующий часовой пояс" in response.text
    assert PASSWORD not in response.text


@pytest.mark.parametrize("username", ["ab", "a" * 31, "имя", "has space"])
def test_invalid_username(client, username):
    assert register(client, username).status_code == 400


@pytest.mark.parametrize("password", ["a" * 11, "a" * 129])
def test_password_boundaries(client, password):
    assert register(client, password=password, confirmation=password).status_code == 400


@pytest.mark.parametrize("length", [12, 128])
def test_allowed_password_boundaries(client, length):
    assert register(client, password="a" * length, confirmation="a" * length).status_code == 302


def test_confirmation(client):
    assert register(client, confirmation="different password").status_code == 400


def test_rate_limit(client):
    for _ in range(5):
        assert login(client, password="incorrect").status_code == 400
    response = login(client, password="incorrect")
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"


def test_production_configuration(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app()
    monkeypatch.setenv("SECRET_KEY", "test-production-key")
    app = create_app()
    assert app.config["SESSION_COOKIE_SECURE"]
    assert app.config["SESSION_COOKIE_HTTPONLY"]
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert app.debug is False


def test_health_cookies_and_proxy(app, client):
    response = client.get("/health")
    assert response.json == {"status": "ok"}
    assert response.status_code == 200
    assert not app.config["SESSION_COOKIE_SECURE"]
    register(client)
    response = login(client)
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie and "Secure;" not in cookie
    # Forwarded headers must not change the observed client address.
    limited = app.extensions["login_limiter"]
    limited.buckets.clear()
    for i in range(5):
        client.post("/login", data={"csrf_token": token(client, "/login")}, headers={"X-Forwarded-For": f"10.0.0.{i}"})
    assert login(client).status_code == 429
