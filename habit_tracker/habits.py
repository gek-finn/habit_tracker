import calendar
import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from .db import get_db
from .statistics import calculate_stats

bp = Blueprint("habits", __name__)
MIN_DATE = date(2000, 1, 1)
MONTHS = ("", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь")


def user_today():
    clock = current_app.config.get("UTC_NOW", lambda: datetime.now(timezone.utc))
    return clock().astimezone(ZoneInfo(current_user.timezone)).date()


def parse_day(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("Invalid date")
    return date.fromisoformat(value)


def owned_habit(habit_id):
    habit = get_db().execute("SELECT * FROM habits WHERE id=? AND user_id=?", (habit_id, current_user.id)).fetchone()
    if habit is None:
        abort(404)
    return habit


def archive_mode():
    if len(request.args.getlist("view")) > 1 or request.args.get("view", "active") not in {"active", "archive"}:
        abort(400, description="Выберите активные привычки или архив.")
    return request.args.get("view", "active") == "archive"


def month_url(first, archived=False):
    params = {"year": first.year, "month": first.month}
    if archived:
        params["view"] = "archive"
    return url_for("auth.tracker", **params)


def selected_month(today):
    year_raw, month_raw = request.args.get("year"), request.args.get("month")
    if year_raw is None and month_raw is None:
        year, month = today.year, today.month
    else:
        if (len(request.args.getlist("year")) != 1 or len(request.args.getlist("month")) != 1
                or not re.fullmatch(r"[0-9]{4}", year_raw or "")
                or not re.fullmatch(r"[0-9]{1,2}", month_raw or "")):
            abort(400, description="Укажите корректные год и месяц.")
        year, month = int(year_raw), int(month_raw)
    try:
        first = date(year, month, 1)
    except ValueError:
        abort(400, description="Укажите корректные год и месяц.")
    current_month = today.replace(day=1)
    if first < MIN_DATE or first > current_month:
        abort(400, description="Месяц вне разрешённого диапазона.")
    return first, date(year, month, calendar.monthrange(year, month)[1])


def history_for(habit):
    return [date.fromisoformat(row["day"]) for row in get_db().execute(
        "SELECT day FROM completions WHERE habit_id=? ORDER BY day", (habit["id"],))]


def calendar_page():
    today = user_today()
    first, last = selected_month(today)
    archived = archive_mode()
    year, month = first.year, first.month
    days = [date(year, month, day) for day in range(1, last.day + 1)]
    db = get_db()
    # A single read snapshot and two queries, independent of habit/day count.
    with db:
        db.execute("BEGIN")
        condition = "IS NOT NULL" if archived else "IS NULL"
        habits = db.execute(f"SELECT * FROM habits WHERE user_id=? AND start_date<=? AND archived_on {condition} ORDER BY created_at,id",
                            (current_user.id, last.isoformat())).fetchall()
        histories = {habit["id"]: [] for habit in habits}
        rows = db.execute(f"SELECT c.habit_id,c.day FROM completions c JOIN habits h ON h.id=c.habit_id WHERE h.user_id=? AND h.start_date<=? AND h.archived_on {condition} AND c.day<=? ORDER BY c.habit_id,c.day",
                          (current_user.id, last.isoformat(), today.isoformat())).fetchall()
        for row in rows:
            histories[row["habit_id"]].append(date.fromisoformat(row["day"]))
    stats = {habit["id"]: calculate_stats(habit, histories[habit["id"]], first, last, today) for habit in habits}
    done = {(habit_id, day.isoformat()) for habit_id, history in histories.items() for day in history if first <= day <= last}
    previous = date(year-1, 12, 1) if month == 1 else date(year, month-1, 1)
    following = date(year+1, 1, 1) if month == 12 and year < 9999 else (date(year, month+1, 1) if month < 12 else None)
    return render_template("tracker.html", title="Архив привычек" if archived else "Мой трекер", habits=habits, days=days, done=done, today=today,
                           stats=stats, archived=archived, first=first, last=last,
                           active_url=month_url(first), archive_url=month_url(first, True),
                           month_label=f"{MONTHS[month]} {year}", current_url=month_url(today.replace(day=1), archived),
                           previous_url=month_url(previous, archived) if first > MIN_DATE else None,
                           next_url=month_url(following, archived) if following and first < today.replace(day=1) else None)



@bp.route("/habits/new", methods=["GET", "POST"])
@login_required
def create():
    return habit_form()


@bp.route("/habits/<int:habit_id>/edit", methods=["GET", "POST"])
@login_required
def edit(habit_id):
    habit = owned_habit(habit_id)
    if habit["archived_on"]:
        abort(409, description="Архивную привычку нельзя редактировать.")
    return habit_form(habit)


def habit_form(habit=None):
    today = user_today()
    name = habit["name"] if habit else ""
    description = habit["description"] if habit else ""
    start = habit["start_date"] if habit else today.isoformat()
    errors = []
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "")
        if not 1 <= len(name) <= 80:
            errors.append("Название должно содержать от 1 до 80 символов после удаления пробелов по краям.")
        if len(description) > 300:
            errors.append("Описание должно содержать не более 300 символов.")
        if habit:
            if "start_date" in request.form and request.form["start_date"] != start:
                errors.append("Дату начала существующей привычки менять нельзя.")
        else:
            start = request.form.get("start_date", "")
            try:
                start_day = parse_day(start)
                if not MIN_DATE <= start_day <= today:
                    raise ValueError()
            except ValueError:
                errors.append("Укажите дату начала с 01.01.2000 до сегодняшнего дня в вашем часовом поясе.")
        if not errors:
            db = get_db()
            with db:
                db.execute("BEGIN IMMEDIATE")
                if habit:
                    if owned_habit(habit["id"])["archived_on"]:
                        abort(409, description="Архивную привычку нельзя редактировать.")
                    db.execute("UPDATE habits SET name=?, description=? WHERE id=? AND user_id=?", (name, description, habit["id"], current_user.id))
                else:
                    db.execute("INSERT INTO habits(user_id,name,description,start_date) VALUES (?,?,?,?)", (current_user.id, name, description, start))
            flash("Привычка сохранена.")
            return redirect(url_for("auth.tracker"))
    return render_template("habit_form.html", title="Редактировать привычку" if habit else "Новая привычка", habit=habit,
                           name=name, description=description, start=start, today=today.isoformat(), errors=errors), (400 if errors else 200)


@bp.route("/habits/<int:habit_id>/completion", methods=["GET", "POST"])
@login_required
def completion(habit_id):
    db = get_db()
    today = user_today()
    first, last = selected_month(today)
    with db:
        db.execute("BEGIN IMMEDIATE" if request.method == "POST" else "BEGIN")
        habit = owned_habit(habit_id)
        if request.method == "POST" and habit["archived_on"]:
            return jsonify(error="Архивная привычка доступна только для чтения."), 409
        data = request.get_json(silent=True) if request.method == "POST" else request.args
        if request.method == "POST" and (not isinstance(data, dict) or type(data.get("completed")) is not bool):
            return jsonify(error="Укажите желаемое состояние отметки."), 400
        end = min(today, date.fromisoformat(habit["archived_on"])) if habit["archived_on"] else today
        try:
            day = parse_day(data.get("date"))
            if not max(MIN_DATE, date.fromisoformat(habit["start_date"])) <= day <= end:
                raise ValueError()
        except ValueError:
            return jsonify(error="Эта дата недоступна для отметки."), 400
        if request.method == "POST":
            if data["completed"]:
                db.execute("INSERT INTO completions(habit_id,day) VALUES (?,?) ON CONFLICT(habit_id,day) DO NOTHING", (habit_id, day.isoformat()))
            else:
                db.execute("DELETE FROM completions WHERE habit_id=? AND day=?", (habit_id, day.isoformat()))
        history = history_for(habit)
        stats = calculate_stats(habit, history, first, last, today)
        result = {"completed": day in history, "date": day.isoformat(), "stats": stats,
                  "archived": bool(habit["archived_on"])}
    return jsonify(result)


@bp.route("/habits/<int:habit_id>/archive", methods=["GET", "POST"])
@login_required
def archive(habit_id):
    if request.method == "GET":
        habit = owned_habit(habit_id)
        return render_template("archive_confirm.html", title="Архивировать привычку", habit=habit)
    if request.form.get("confirmation") != "archive":
        owned_habit(habit_id)
        abort(400, description="Подтвердите архивирование привычки.")
    db = get_db()
    with db:
        db.execute("BEGIN IMMEDIATE")
        owned_habit(habit_id)
        db.execute("UPDATE habits SET archived_on=COALESCE(archived_on,?) WHERE id=? AND user_id=?", (user_today().isoformat(), habit_id, current_user.id))
    flash("Привычка в архиве. История сохранена; восстановление в этой версии недоступно.")
    return redirect(url_for("auth.tracker", view="archive"))
