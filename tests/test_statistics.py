from datetime import date, timedelta
import pytest
from habit_tracker.statistics import calculate_stats


def stats(start, days, today, first=None, last=None, archived=None):
    habit = {"start_date": start, "archived_on": archived}
    today = date.fromisoformat(today)
    return calculate_stats(habit, [date.fromisoformat(day) for day in days],
                           date.fromisoformat(first) if first else today.replace(day=1),
                           date.fromisoformat(last) if last else today, today)


def test_no_available_days():
    result = stats("2026-11-10", [], "2026-11-14", "2026-10-01", "2026-10-31")
    assert result == dict(completed_days=0, available_days=0, percentage=None, current_streak=0, best_streak=0)


def test_mid_month_and_today_in_denominator():
    result = stats("2026-11-10", ["2026-11-10", "2026-11-11"], "2026-11-14", last="2026-11-30")
    assert result["available_days"] == 5
    assert result["completed_days"] == 2
    assert result["percentage"] == 40


@pytest.mark.parametrize("day_count,count,expected", [(8,1,13),(6,1,17),(7,1,14),(16,2,13),(8,0,0),(8,8,100)])
def test_round_half_up(day_count, count, expected):
    days = [(date(2026,5,1)+timedelta(days=i)).isoformat() for i in range(count)]
    assert stats("2026-05-01", days, f"2026-05-{day_count:02}")["percentage"] == expected


@pytest.mark.parametrize("days,expected", [
    (["2026-11-12","2026-11-13","2026-11-14"],3),
    (["2026-11-11","2026-11-12","2026-11-13"],3),
    (["2026-11-11","2026-11-12"],0),
    (["2026-11-12","2026-11-14"],1),([],0)])
def test_current_streak(days, expected):
    assert stats("2026-11-01", days, "2026-11-14")["current_streak"] == expected


@pytest.mark.parametrize("start,end", [("2026-10-30","2026-11-02"),("2025-12-30","2026-01-02"),("2024-02-28","2024-03-02")])
def test_best_streak_across_boundaries(start,end):
    begin, finish = date.fromisoformat(start),date.fromisoformat(end)
    days = [(begin+timedelta(days=i)).isoformat() for i in range((finish-begin).days+1)]
    result = stats(start, days, "2026-11-14")
    assert result["best_streak"] == len(days)


def test_archived_cutoff_inclusive_and_no_data_later():
    result = stats("2026-10-01", ["2026-10-02","2026-10-03","2026-10-04"], "2026-11-14", "2026-10-01", "2026-10-31", "2026-10-03")
    assert result == dict(completed_days=2,available_days=3,percentage=67,current_streak=None,best_streak=2)
    result = stats("2026-10-01", ["2026-10-02"], "2026-11-14", archived="2026-10-03")
    assert result["percentage"] is None and result["available_days"] == 0


def test_ignore_days_outside_available_period():
    result = stats("2026-11-12", ["2026-11-11","2026-11-12","2026-11-15"], "2026-11-14")
    assert result["completed_days"] == 1 and result["best_streak"] == 1
