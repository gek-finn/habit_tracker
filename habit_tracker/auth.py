import re
import sqlite3
import time
from collections import OrderedDict, deque
from threading import Lock
from urllib.parse import urlsplit
from zoneinfo import available_timezones
from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import UserMixin, current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash
from .db import get_db

bp = Blueprint("auth", __name__)
TIMEZONES = sorted(available_timezones())
DUMMY_HASH = generate_password_hash("dummy-password-for-timing")


class User(UserMixin):
    def __init__(self, row):
        self.id = row["id"]
        self.username = row["username"]
        self.timezone = row["timezone"]


class LoginLimiter:
    """Five attempts per IP per 60 seconds; bounded process-local memory."""
    def __init__(self):
        self.buckets = OrderedDict()
        self.lock = Lock()

    def allow(self, key):
        now = time.monotonic()
        with self.lock:
            while self.buckets and next(iter(self.buckets.values()))[-1] <= now - 60:
                self.buckets.popitem(last=False)
            attempts = self.buckets.pop(key, deque())
            while attempts and attempts[0] <= now - 60:
                attempts.popleft()
            allowed = len(attempts) < 5
            if allowed:
                attempts.append(now)
            self.buckets[key] = attempts
            if len(self.buckets) > 10000:
                self.buckets.popitem(last=False)
            return allowed


def safe_next(value):
    if not value or not value.startswith("/") or value.startswith("//"):
        return None
    if "\\" in value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    parsed = urlsplit(value)
    return value if not parsed.scheme and not parsed.netloc else None


@bp.route("/register", methods=["GET", "POST"])
def register():
    errors = []
    username = request.form.get("username", "")
    timezone = request.form.get("timezone", "Europe/Kaliningrad")
    if request.method == "POST":
        password = request.form.get("password", "")
        if not re.fullmatch(r"[A-Za-z0-9_]{3,30}", username):
            errors.append("Имя пользователя: 3–30 латинских букв, цифр или знаков подчёркивания.")
        if not 12 <= len(password) <= 128:
            errors.append("Пароль должен содержать от 12 до 128 символов.")
        if password != request.form.get("confirmation", ""):
            errors.append("Пароли не совпадают.")
        if timezone not in TIMEZONES:
            errors.append("Выберите существующий часовой пояс из списка.")
        if not errors:
            db = get_db()
            try:
                db.execute("INSERT INTO users (username, username_key, password_hash, timezone) VALUES (?, ?, ?, ?)",
                           (username, username.lower(), generate_password_hash(password), timezone))
                db.commit()
            except sqlite3.IntegrityError:
                db.rollback()
                errors.append("Это имя пользователя уже занято.")
            else:
                flash("Регистрация завершена. Войдите в свой аккаунт.")
                return redirect(url_for("auth.login"))
    return render_template("register.html", title="Создать аккаунт", errors=errors, username=username, timezone=timezone, timezones=TIMEZONES), (400 if errors else 200)


@bp.route("/login", methods=["GET", "POST"])
def login():
    errors = []
    if request.method == "POST":
        if not current_app.extensions["login_limiter"].allow(request.remote_addr or "unknown"):
            return render_template("login.html", title="Войти", errors=["Слишком много попыток входа. Повторите через минуту."]), 429, {"Retry-After": "60"}
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        row = get_db().execute("SELECT * FROM users WHERE username_key = ?", (username.lower(),)).fetchone()
        valid = check_password_hash(row["password_hash"] if row else DUMMY_HASH, password)
        if row and valid:
            session.clear()
            login_user(User(row))
            return redirect(safe_next(request.args.get("next")) or url_for("auth.tracker"))
        errors.append("Неверное имя пользователя или пароль")
    return render_template("login.html", title="Войти", errors=errors), (400 if errors else 200)


@bp.get("/tracker")
@login_required
def tracker():
    from .habits import calendar_page
    return calendar_page()


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for("index"))
