import sqlite3
from datetime import datetime, timezone
import pytest
from test_app import app, client, login, register, token
from habit_tracker.db import get_db, upgrade_db


@pytest.fixture
def user(app, client):
    app.config["UTC_NOW"] = lambda: datetime(2026, 11, 14, 10, tzinfo=timezone.utc)
    register(client)
    login(client)
    return client


def create(client, **overrides):
    data = dict(name="Читать", description="10 страниц", start_date="2026-11-01")
    data.update(overrides)
    data["csrf_token"] = token(client, "/habits/new")
    return client.post("/habits/new", data=data)


def mark(client, habit=1, day="2026-11-14", completed=True, csrf=True):
    headers = {"X-CSRFToken": token(client, "/tracker")} if csrf else {}
    return client.post(f"/habits/{habit}/completion", json={"date": day, "completed": completed}, headers=headers)


def test_create_edit_and_stable_order(app, user):
    assert create(user, name="  Читать  ").status_code == 302
    assert create(user, name="Читать").status_code == 302
    with app.app_context():
        rows = get_db().execute("SELECT * FROM habits ORDER BY created_at,id").fetchall()
        assert [r["name"] for r in rows] == ["Читать", "Читать"]
        assert rows[0]["user_id"] == 1
    page = user.get("/habits/1/edit")
    assert "Дата начала" in page.text and 'name="start_date"' not in page.text
    response = user.post("/habits/1/edit", data={"name": "Новое имя", "description": "Описание", "csrf_token": token(user, "/habits/1/edit")})
    assert response.status_code == 302
    assert "Новое имя" in user.get("/tracker").text
    with app.app_context():
        assert get_db().execute("SELECT start_date FROM habits WHERE id=1").fetchone()[0] == "2026-11-01"


@pytest.mark.parametrize("data", [{"name": " "}, {"name": "x"*81}, {"description": "x"*301}, {"start_date": ""}, {"start_date": "2026-11-15"}, {"start_date": "1999-12-31"}, {"start_date": "2025-02-29"}, {"start_date": "2026-1-01"}])
def test_validation(app, user, data):
    assert create(user, **data).status_code == 400
    with app.app_context():
        assert get_db().execute("SELECT count(*) FROM habits").fetchone()[0] == 0


def test_valid_boundaries_and_default_date(user):
    assert 'value="2026-11-14"' in user.get("/habits/new").text
    assert create(user, name="x"*80, description="x"*300, start_date="2000-01-01").status_code == 302


def test_forged_start_date(app, user):
    create(user)
    response = user.post("/habits/1/edit", data={"name": "Hacked", "start_date": "2026-10-01", "csrf_token": token(user, "/habits/1/edit")})
    assert response.status_code == 400
    with app.app_context():
        row = get_db().execute("SELECT * FROM habits WHERE id=1").fetchone()
        assert row["start_date"] == "2026-11-01" and row["name"] == "Читать"


def test_foreign_access(app, user):
    create(user, name="Секрет владельца")
    mark(user)
    other = app.test_client()
    register(other, "Other")
    login(other, "Other")
    assert "Секрет владельца" not in other.get("/tracker").text
    assert other.get("/habits/1/edit").status_code == 404
    csrf = token(other, "/habits/new")
    assert other.post("/habits/1/edit", data={"name":"stolen", "csrf_token":csrf}).status_code == 404
    assert other.get("/habits/1/completion?date=2026-11-14").status_code == 404
    assert mark(other, completed=False).status_code == 404
    with app.app_context():
        assert get_db().execute("SELECT count(*) FROM completions").fetchone()[0] == 1


def test_marks_idempotent_and_persist(app, user):
    create(user)
    for _ in range(2):
        assert mark(user).json["completed"] is True
    assert user.get("/habits/1/completion?date=2026-11-14").json["completed"] is True
    page = user.get("/tracker").text
    assert 'aria-pressed="true"' in page
    with app.app_context():
        db = get_db()
        assert db.execute("SELECT count(*) FROM completions").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO completions VALUES (1, '2026-11-14')")
        db.rollback()
    for _ in range(2):
        assert mark(user, completed=False).json["completed"] is False
    assert 'aria-pressed="true"' not in user.get("/tracker").text


@pytest.mark.parametrize("day", ["2026-11-15", "2026-10-31", "1999-01-01", "bad", "2026-02-30"])
def test_unavailable_mark(user, day):
    create(user)
    assert mark(user, day=day).status_code == 400
    assert user.get(f"/habits/1/completion?date={day}").status_code == 400


@pytest.mark.parametrize("completed", [1, "true", None, [], {}])
def test_explicit_boolean(user, completed):
    create(user)
    assert mark(user, completed=completed).status_code == 400


@pytest.mark.parametrize("year,month,count", [(2024,2,29),(2025,2,28),(2000,2,29)])
def test_february(user, year, month, count):
    create(user, start_date="2000-01-01")
    text = user.get(f"/tracker?year={year}&month={month}").text
    assert f'data-date="{year}-02-{count}"' in text
    assert f'data-date="{year}-02-{count+1}"' not in text


def test_december_january_and_limits(user):
    create(user)
    december = user.get("/tracker?year=2025&month=12").text
    assert "year=2026&amp;month=1" in december
    january = user.get("/tracker?year=2026&month=1").text
    assert "year=2025&amp;month=12" in january
    earliest = user.get("/tracker?year=2000&month=1").text
    assert 'aria-label="Предыдущий месяц"' not in earliest
    assert 'aria-label="Следующий месяц"' not in user.get("/tracker").text


@pytest.mark.parametrize("query", ["year=1999&month=12", "year=2026&month=12", "year=2025&month=13", "year=2025&month=0", "year=0000&month=1", "year=abc&month=1", "year=2025", "month=1", "year=2025&month=1.5", "year=2025&year=2024&month=1", "year=999999999999&month=1"])
def test_invalid_month(user, query):
    assert user.get("/tracker?"+query).status_code == 400


def test_month_filter_and_disabled_days(user):
    create(user, start_date="2026-11-10")
    assert "Читать" not in user.get("/tracker?year=2026&month=10").text
    text = user.get("/tracker").text
    assert 'data-date="2026-11-09"' not in text
    assert 'data-date="2026-11-10"' in text
    assert 'data-date="2026-11-15"' not in text


@pytest.mark.parametrize("zone,expected", [("Europe/Kaliningrad","2026-11-15"),("America/New_York","2026-11-14")])
def test_local_today_near_midnight(app, user, zone, expected):
    app.config["UTC_NOW"] = lambda: datetime(2026, 11, 14, 23, 30, tzinfo=timezone.utc)
    with app.app_context():
        with get_db() as db:
            db.execute("UPDATE users SET timezone=? WHERE id=1", (zone,))
    assert f'value="{expected}"' in user.get("/habits/new").text
    assert create(user, start_date=expected).status_code == 302
    assert mark(user, day=expected).status_code == 200
    if expected == "2026-11-14":
        assert mark(user, day="2026-11-15").status_code == 400


def test_upgrade_from_stage1_preserves_all(app):
    # Replace only the TEST database with an actual stage-1 schema.
    old_path = app.config["DATABASE"] + ".old"
    app.config["DATABASE"] = old_path
    with sqlite3.connect(old_path) as db:
        db.execute("CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT NOT NULL,username_key TEXT NOT NULL UNIQUE,password_hash TEXT NOT NULL,timezone TEXT NOT NULL)")
        db.execute("INSERT INTO users VALUES (1,'Existing','existing','original hash','Europe/Kaliningrad')")
    runner = app.test_cli_runner()
    assert runner.invoke(args=["upgrade-db"]).exit_code == 0
    with app.app_context():
        with get_db() as db:
            db.execute("INSERT INTO habits(user_id,name,start_date) VALUES (1,'Keep','2026-01-01')")
            db.execute("INSERT INTO completions VALUES (1,'2026-01-01')")
    assert runner.invoke(args=["upgrade-db"]).exit_code == 0
    with app.app_context():
        assert tuple(get_db().execute("SELECT * FROM users").fetchone()) == (1,'Existing','existing','original hash','Europe/Kaliningrad')
        assert get_db().execute("SELECT count(*) FROM habits").fetchone()[0] == 1
        assert get_db().execute("SELECT count(*) FROM completions").fetchone()[0] == 1


def test_new_routes_csrf(user):
    create(user)
    assert user.post("/habits/new", data={"name":"x"}).status_code == 400
    assert user.post("/habits/1/edit", data={"name":"x"}).status_code == 400
    assert mark(user, csrf=False).status_code == 400
    assert user.post("/habits/1/completion", json={"date":"2026-11-14","completed":True}, headers={"X-CSRFToken":"bad"}).status_code == 400


@pytest.mark.parametrize("data", [{"name":" "},{"name":"x"*81},{"name":"Valid","description":"x"*301}])
def test_edit_validation(app, user, data):
    create(user)
    data["csrf_token"] = token(user, "/habits/1/edit")
    assert user.post("/habits/1/edit", data=data).status_code == 400
    with app.app_context():
        assert get_db().execute("SELECT name FROM habits WHERE id=1").fetchone()[0] == "Читать"


def test_new_pages_require_login(client):
    assert client.get("/habits/new").status_code == 302
    assert client.get("/habits/1/edit").status_code == 302
    assert client.get("/habits/1/completion?date=2026-11-14").status_code == 302
