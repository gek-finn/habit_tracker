import os
import secrets
from pathlib import Path
from flask import Flask, render_template
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect, CSRFError
from .db import close_db, get_db, init_db_command, upgrade_db_command


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    mode = os.environ.get("APP_ENV", "development")
    if mode not in {"development", "production"}:
        raise RuntimeError("APP_ENV должен быть development или production")
    secret = os.environ.get("SECRET_KEY")
    if mode == "production" and (not secret or not secret.strip()):
        raise RuntimeError("Для публикации задайте SECRET_KEY в окружении")
    app.config.from_mapping(
        SECRET_KEY=secret or secrets.token_hex(32),
        DATABASE=str(Path(os.environ.get("DATABASE_PATH") or Path(app.instance_path) / "habit_tracker.sqlite3").resolve()),
        DEBUG=False,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=mode == "production",
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=32 * 1024,
    )
    if test_config:
        app.config.update(test_config)
    trust_proxy = os.environ.get("TRUST_PROXY_HEADERS", "0")
    if trust_proxy not in {"0", "1"}:
        raise RuntimeError("TRUST_PROXY_HEADERS должен быть 0 или 1")
    hosts = os.environ.get("TRUSTED_HOSTS", "")
    app.config["TRUSTED_HOSTS"] = [host.strip() for host in hosts.split(",") if host.strip()] or None
    if trust_proxy == "1":
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=0, x_port=0, x_prefix=0)
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    app.cli.add_command(upgrade_db_command)
    from .habits import bp as habits_bp
    app.register_blueprint(habits_bp)
    CSRFProtect(app)
    login = LoginManager(app)
    login.login_view = "auth.login"
    login.login_message = "Войдите, чтобы открыть свой трекер."
    from .auth import User, bp, LoginLimiter
    app.extensions["login_limiter"] = LoginLimiter()
    app.register_blueprint(bp)

    @login.user_loader
    def load_user(user_id):
        row = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return User(row) if row else None

    @app.get("/")
    def index():
        return render_template("index.html", title="Ежедневные привычки")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        return render_template("error.html", title="Обновите страницу", message="Срок действия формы истёк или защитный код отсутствует. Обновите страницу и попробуйте ещё раз."), 400

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
        response.headers["Cache-Control"] = "no-store"
        return response

    return app
