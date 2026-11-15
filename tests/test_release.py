import pytest
from habit_tracker import create_app
from test_app import app, client, register, login


def test_production_rejects_blank_key(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "   ")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app()


def test_proxy_is_explicit_and_host_is_checked(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "0")
    app=create_app({"TESTING":True})
    with app.test_request_context("/", headers={"X-Forwarded-For":"203.0.113.7","X-Forwarded-Proto":"https"}):
        from flask import request
        assert request.scheme=="http"
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "1")
    monkeypatch.setenv("TRUSTED_HOSTS", "habits.gilinsky.ru")
    app=create_app({"TESTING":True})
    @app.get("/test-proxy")
    def inspect_proxy():
        from flask import request
        return {"scheme":request.scheme,"ip":request.remote_addr}
    client=app.test_client()
    headers={"Host":"habits.gilinsky.ru","X-Forwarded-For":"203.0.113.7","X-Forwarded-Proto":"https"}
    assert client.get("/test-proxy",headers=headers).json=={"scheme":"https","ip":"203.0.113.7"}
    assert client.get("/health",headers={"Host":"other.example"}).status_code==400


def test_invalid_proxy_setting(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS","yes")
    with pytest.raises(RuntimeError,match="TRUST_PROXY_HEADERS"):
        create_app()


def test_production_cookie_on_https_and_no_debug(app,monkeypatch):
    monkeypatch.setenv("APP_ENV","production")
    monkeypatch.setenv("SECRET_KEY","test-only-production-key")
    production=create_app({"TESTING":True,"DATABASE":app.config["DATABASE"]})
    client=production.test_client()
    response=client.get("/login",base_url="https://localhost")
    cookie=response.headers["Set-Cookie"]
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=Lax" in cookie
    assert not production.debug
    assert production.test_client().get("/health").json=={"status":"ok"}


def test_failed_mark_then_retry_keeps_statistics(client):
    register(client)
    login(client)
    from test_habits import create, mark
    create(client,start_date="2000-01-01")
    assert mark(client,day="2999-01-01").status_code==400
    response=mark(client,day="2000-01-01")
    assert response.status_code==200 and response.json["completed"]
    assert response.json["stats"]==client.get("/habits/1/completion?date=2000-01-01").json["stats"]


def test_full_local_acceptance(app,client):
    from datetime import datetime,timezone
    from test_app import token
    from test_habits import create,mark
    from test_archive import archive
    app.config["UTC_NOW"]=lambda:datetime(2026,11,15,10,tzinfo=timezone.utc)
    assert register(client).status_code==302
    assert login(client).status_code==302
    assert create(client,start_date="2026-11-15").status_code==302
    result=mark(client,day="2026-11-15")
    assert result.json["stats"]==dict(completed_days=1,available_days=1,percentage=100,current_streak=1,best_streak=1)
    assert '1 из 1 · 100%' in client.get("/tracker").text
    assert archive(client).status_code==302
    assert 'class="day-button' not in client.get("/tracker?view=archive").text
    assert '1 из 1 · 100%' in client.get("/tracker?view=archive").text
    assert client.get("/habits/1/edit").status_code==409
    response=client.post("/logout",data={"csrf_token":token(client,"/tracker")})
    assert response.status_code==302
    assert client.get("/tracker").status_code==302
