import sqlite3
from pathlib import Path
import click
from flask import current_app, g
from flask.cli import with_appcontext


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"], timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    Path(current_app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    db = get_db()
    db.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT NOT NULL,
        username_key TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        timezone TEXT NOT NULL
    )""")
    db.commit()
    upgrade_db()


@click.command("init-db")
@with_appcontext
def init_db_command():
    """Create missing tables without removing existing data."""
    init_db()
    click.echo("База подготовлена. Существующие данные сохранены.")


def upgrade_db():
    """Upgrade the small application schema atomically; never replace existing records."""
    db = get_db()
    with db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("""CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 80),
            description TEXT NOT NULL DEFAULT '' CHECK(length(description) <= 300),
            start_date TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )""")
        columns = {row["name"] for row in db.execute("PRAGMA table_info(habits)")}
        if "archived_on" not in columns:
            db.execute("ALTER TABLE habits ADD COLUMN archived_on TEXT")
        db.execute("CREATE INDEX IF NOT EXISTS habits_owner_order ON habits(user_id, created_at, id)")
        db.execute("""CREATE TABLE IF NOT EXISTS completions (
            habit_id INTEGER NOT NULL REFERENCES habits(id),
            day TEXT NOT NULL,
            PRIMARY KEY (habit_id, day)
        )""")


@click.command("upgrade-db")
@with_appcontext
def upgrade_db_command():
    """Upgrade schema while preserving users and history."""
    db = get_db()
    if not db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'").fetchone():
        raise click.ClickException("Сначала выполните init-db для новой базы.")
    upgrade_db()
    click.echo("Структура обновлена. Пользователи и данные сохранены.")
