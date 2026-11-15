import sqlite3
from datetime import datetime, timezone
import pytest
from test_app import app, client, token, register, login
from test_habits import user, create, mark
from habit_tracker.db import get_db


def archive(client, habit=1, csrf=True, confirmed=True):
    data = {"confirmation": "archive"} if confirmed else {}
    if csrf:
        data["csrf_token"] = token(client, "/habits/new")
    return client.post(f"/habits/{habit}/archive", data=data)


def test_mark_stats_match_get_and_recalculate(user):
    create(user, start_date="2026-11-10")
    assert mark(user,day="2026-11-12").json["stats"]["current_streak"] == 0
    response = mark(user,day="2026-11-13")
    assert response.json["stats"]["current_streak"] == 2
    response = mark(user)
    expected = dict(completed_days=3,available_days=5,percentage=60,current_streak=3,best_streak=3)
    assert response.json["stats"] == expected
    assert user.get("/habits/1/completion?date=2026-11-14").json["stats"] == expected
    page = user.get("/tracker").text
    assert 'data-stat="summary">3 из 5 · 60%' in page
    assert 'data-stat="current_streak">3<' in page
    result = mark(user,day="2026-11-13",completed=False).json["stats"]
    assert result == dict(completed_days=2,available_days=5,percentage=40,current_streak=1,best_streak=1)
    assert user.get("/habits/1/completion?date=2026-11-14").json["stats"] == result
    assert 'data-stat="summary">2 из 5 · 40%' in user.get("/tracker").text


def test_selected_month_in_update_response(user):
    create(user,start_date="2026-10-30")
    headers={"X-CSRFToken":token(user,"/tracker")}
    response=user.post("/habits/1/completion?year=2026&month=10",json={"date":"2026-10-31","completed":True},headers=headers)
    assert response.json["stats"]["completed_days"] == 1
    assert response.json["stats"]["available_days"] == 2
    assert 'data-stat="summary">1 из 2 · 50%' in user.get("/tracker?year=2026&month=10").text
    assert user.get("/habits/1/completion?year=2026&month=10&date=2026-10-31").json["stats"] == response.json["stats"]


def test_archive_preserves_history_and_date(app,user):
    create(user,name="Личная привычка для архива",start_date="2026-11-10")
    mark(user)
    confirmation=user.get("/habits/1/archive")
    assert "восстановление" in confirmation.text.lower() and "основного списка" in confirmation.text
    assert archive(user,confirmed=False).status_code == 400
    assert archive(user).status_code == 302
    app.config["UTC_NOW"] = lambda: datetime(2026,11,15,10,tzinfo=timezone.utc)
    assert archive(user).status_code == 302
    with app.app_context():
        row=get_db().execute("SELECT * FROM habits WHERE id=1").fetchone()
        assert row["archived_on"] == "2026-11-14"
        assert row["name"] == "Личная привычка для архива"
        assert get_db().execute("SELECT day FROM completions").fetchone()[0] == "2026-11-14"
    assert "Личная привычка для архива" not in user.get("/tracker").text
    page=user.get("/tracker?view=archive").text
    assert "Личная привычка для архива" in page and "14.11.2026" in page
    assert 'class="day-button' not in page
    assert 'data-stat="current_streak">В архиве<' in page
    assert 'data-stat="summary">1 из 5 · 20%' in page
    assert 'aria-label="Следующий месяц"' not in page
    assert "view=archive" in page
    assert user.get("/habits/1/completion?date=2026-11-15").status_code == 400
    assert user.get("/habits/1/completion?date=2026-11-14").json["completed"] is True


def test_archive_readonly_on_server(app,user):
    create(user)
    mark(user)
    archive(user)
    assert user.get("/habits/1/edit").status_code == 409
    csrf=token(user,"/habits/new")
    assert user.post("/habits/1/edit",data={"csrf_token":csrf,"name":"Changed","description":"Changed"}).status_code == 409
    assert mark(user,completed=False).status_code == 409
    assert mark(user,day="2026-11-13").status_code == 409
    with app.app_context():
        assert get_db().execute("SELECT name FROM habits").fetchone()[0] == "Читать"
        assert get_db().execute("SELECT count(*) FROM completions").fetchone()[0] == 1


def test_foreign_archive_ids_and_queries(app,user):
    create(user,name="Private archive name")
    archive(user)
    other=app.test_client()
    register(other,"Other")
    login(other,"Other")
    assert other.get("/habits/1/archive").status_code == 404
    assert archive(other).status_code == 404
    assert other.get("/habits/1/edit").status_code == 404
    assert other.get("/habits/1/completion?date=2026-11-14&view=archive&user_id=1").status_code == 404
    assert mark(other).status_code == 404
    text=other.get("/tracker?view=archive&user_id=1&habit_id=1").text
    assert "Private archive name" not in text and "нет архивных привычек" in text


def test_archive_csrf_and_anonymous(app,user):
    create(user)
    assert archive(user,csrf=False).status_code == 400
    assert user.post("/habits/1/archive",data={"confirmation":"archive","csrf_token":"bad"}).status_code == 400
    assert app.test_client().get("/habits/1/archive").status_code == 302
    with app.app_context():
        assert get_db().execute("SELECT archived_on FROM habits").fetchone()[0] is None


def test_archive_no_month_days_and_start_filter(app,user):
    create(user,start_date="2026-10-03")
    app.config["UTC_NOW"] = lambda: datetime(2026,10,5,10,tzinfo=timezone.utc)
    archive(user)
    app.config["UTC_NOW"] = lambda: datetime(2026,11,14,10,tzinfo=timezone.utc)
    assert 'data-stat="summary">0 из 0 · Нет данных' in user.get("/tracker?view=archive").text
    assert 'data-stat="summary">0 из 3 · 0%' in user.get("/tracker?view=archive&year=2026&month=10").text
    assert "Читать" not in user.get("/tracker?view=archive&year=2026&month=9").text


@pytest.mark.parametrize("query",["view=other","view=archive&view=active","view=archive&year=2026&month=12","view=archive&year=1999&month=12"])
def test_archive_parameters(user,query):
    assert user.get("/tracker?"+query).status_code == 400


def test_archive_date_uses_user_timezone(app,user):
    create(user)
    app.config["UTC_NOW"]=lambda:datetime(2026,11,14,23,30,tzinfo=timezone.utc)
    archive(user)
    with app.app_context():
        assert get_db().execute("SELECT archived_on FROM habits").fetchone()[0] == "2026-11-15"


def test_upgrade_stage2_preserves_data_and_repeats(app,tmp_path):
    path=tmp_path/"stage2.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript("""CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT,username_key TEXT,password_hash TEXT,timezone TEXT);
        CREATE TABLE habits(id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES users(id),name TEXT,description TEXT,start_date TEXT,created_at TEXT);
        CREATE TABLE completions(habit_id INTEGER REFERENCES habits(id),day TEXT,PRIMARY KEY(habit_id,day));
        INSERT INTO users VALUES(1,'Existing','existing','original hash','Europe/Kaliningrad');
        INSERT INTO habits VALUES(1,1,'Keep','Description','2026-11-01','2026-11-01T10:00:00Z');
        INSERT INTO completions VALUES(1,'2026-11-02');""")
        before={table:db.execute(f"SELECT * FROM {table}").fetchall() for table in ("users","habits","completions")}
    app.config["DATABASE"]=str(path)
    runner=app.test_cli_runner()
    for _ in range(2):
        assert runner.invoke(args=["upgrade-db"]).exit_code == 0
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT * FROM users").fetchall()==before["users"]
        assert db.execute("SELECT id,user_id,name,description,start_date,created_at FROM habits").fetchall()==before["habits"]
        assert db.execute("SELECT * FROM completions").fetchall()==before["completions"]
        assert db.execute("SELECT archived_on FROM habits").fetchone()[0] is None
        db.execute("UPDATE habits SET archived_on='2026-11-14'")
    assert runner.invoke(args=["upgrade-db"]).exit_code == 0
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT archived_on FROM habits").fetchone()[0] == '2026-11-14'


def test_new_database_sequence(app,tmp_path):
    app.config["DATABASE"]=str(tmp_path/"new.sqlite3")
    runner=app.test_cli_runner()
    for command in ("init-db","upgrade-db","upgrade-db"):
        assert runner.invoke(args=[command]).exit_code == 0
    with app.app_context():
        assert "archived_on" in {row["name"] for row in get_db().execute("PRAGMA table_info(habits)")}


def test_calendar_does_not_query_each_habit(app,user):
    for i in range(5):
        create(user,name=f"Habit {i}")
    with app.app_context():
        queries=[]
        get_db().set_trace_callback(queries.append)
        assert user.get("/tracker").status_code == 200
    selects=[query for query in queries if query.lstrip().upper().startswith("SELECT")]
    assert len(selects) <= 3  # user loader + habits + all completion histories
