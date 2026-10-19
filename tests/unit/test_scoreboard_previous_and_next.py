"""Unit tests for ScoreboardService.previous_and_next (pure; no DB)."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.domain.enums import MatchStatus, ScheduleType
from app.services.scoreboard_service import ScoreboardService

DAY = datetime(2026, 5, 1)
NOW = DAY + timedelta(hours=18)


def match(name, hour, status=MatchStatus.NOT_STARTED, schedule_type=ScheduleType.STATIC, completed_hour=None):
    start = DAY + timedelta(hours=hour)
    return SimpleNamespace(
        uuid=name,
        name=name,
        schedule_type=schedule_type,
        status=status,
        scheduled_start_time=start,
        nominal_start_time=start,
        completed_time=None if completed_hour is None else DAY + timedelta(hours=completed_hour),
        next_match=None,
    )


def completed(name, hour, schedule_type=ScheduleType.STATIC):
    return match(name, hour, MatchStatus.COMPLETED, schedule_type, completed_hour=hour + 0.5)


def chain(*matches):
    for current, following in zip(matches, matches[1:]):
        current.next_match = following.uuid


def names(field_matches, now=NOW, tz_offset_minutes=None):
    previous, upcoming = ScoreboardService.previous_and_next(field_matches, now, tz_offset_minutes)
    return (previous.name if previous else None, upcoming.name if upcoming else None)


@pytest.mark.unit
def test_next_follows_chain_past_breaks_joins_and_skipped_matches():
    played = completed("Played", 10, ScheduleType.SAFE)
    lunch = match("Lunch", 11, schedule_type=ScheduleType.BREAK)
    join = match("Join", 12, schedule_type=ScheduleType.JOIN)
    skipped = match("Skipped", 12, MatchStatus.SKIPPED, ScheduleType.SAFE)
    upcoming = match("Upcoming", 13, schedule_type=ScheduleType.SAFE)
    chain(played, lunch, join, skipped, upcoming)

    assert names([played, lunch, join, skipped, upcoming]) == ("Played", "Upcoming")


@pytest.mark.unit
def test_chain_link_wins_over_scheduled_order():
    played = completed("Played", 10, ScheduleType.SAFE)
    static_between = match("Static", 11)
    chained = match("Chained", 12, schedule_type=ScheduleType.FAST)
    chain(played, chained)

    assert names([played, static_between, chained]) == ("Played", "Chained")


@pytest.mark.unit
def test_static_match_falls_back_to_scheduled_start_order():
    earlier = completed("Earlier", 9)
    played = completed("Played", 10)
    statbreak = match("Statbreak", 10.5, schedule_type=ScheduleType.STATBREAK)
    following = match("Following", 11)
    later = match("Later", 12)

    assert names([later, following, statbreak, played, earlier]) == ("Played", "Following")


@pytest.mark.unit
def test_end_of_chain_falls_back_to_scheduled_start_order():
    played = completed("Played", 10, ScheduleType.SAFE)
    trailing_break = match("Break", 11, schedule_type=ScheduleType.BREAK)
    static_after = match("Static", 12)
    chain(played, trailing_break)

    assert names([played, trailing_break, static_after]) == ("Played", "Static")


@pytest.mark.unit
def test_previous_is_latest_completion_not_latest_schedule_or_skip():
    played_late = match("Played late", 9, MatchStatus.COMPLETED, completed_hour=12)
    played_on_time = completed("On time", 10)
    skipped_last = match("Skipped", 11, MatchStatus.SKIPPED, completed_hour=13)
    upcoming = match("Upcoming", 14)

    assert names([played_late, played_on_time, skipped_last, upcoming]) == ("Played late", "Upcoming")


@pytest.mark.unit
def test_before_any_completion_next_is_first_unfinished_by_schedule():
    lunch = match("Lunch", 9, schedule_type=ScheduleType.BREAK)
    first = match("First", 10)
    second = match("Second", 11)

    assert names([second, first, lunch]) == (None, "First")


@pytest.mark.unit
def test_tz_offset_limits_matches_to_the_viewers_local_day():
    pacific = -7 * 60
    # Local times: 23:00 on April 30, then 23:30 on May 1, with now at 11:00 on May 1.
    yesterday = match("Yesterday", 6, MatchStatus.COMPLETED, completed_hour=6)
    tonight = match("Tonight", 30.5)

    assert names([yesterday, tonight], tz_offset_minutes=pacific) == (None, "Tonight")
    assert names([yesterday, tonight], tz_offset_minutes=0) == ("Yesterday", None)
    assert names([yesterday, tonight]) == ("Yesterday", "Tonight")
