"""Derived statistics only: no persisted counters and no per-day queries."""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP


def calculate_stats(habit, completed_days, first, last, today):
    start = date.fromisoformat(habit["start_date"])
    archived = habit["archived_on"]
    end = min(today, date.fromisoformat(archived)) if archived else today
    days = sorted({day for day in completed_days if start <= day <= end})
    period_start, period_end = max(first, start), min(last, end)
    available = max(0, (period_end - period_start).days + 1)
    count = sum(period_start <= day <= period_end for day in days)
    percentage = int((Decimal(count * 100) / Decimal(available)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) if available else None
    best = run = 0
    previous = None
    for day in days:
        run = run + 1 if previous is not None and (day - previous).days == 1 else 1
        best = max(best, run)
        previous = day
    current = None if archived else 0
    if not archived:
        done = set(days)
        anchor = today if today in done else today - timedelta(days=1)
        while anchor in done:
            current += 1
            anchor -= timedelta(days=1)
    return {"completed_days": count, "available_days": available, "percentage": percentage,
            "current_streak": current, "best_streak": best}
