"""Live scoreboard state of a tournament field.

Backs both the public scoreboard (``/_api/scoreboard-state``, consumed by
OBS overlays) and the public API's field scoreboard. While a match is in
progress on the field, the state carries that match, its points, and the
per-set scores; while the field is idle, it carries the previous and next
matches instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.enums import STRUCTURAL_SCHEDULE_TYPES, MatchStatus, WinnerSide


@dataclass(frozen=True)
class ScoreboardSide:
    """How one side of a match is displayed on the scoreboard."""

    name: str | None
    shortname: str | None
    photo: str | None


@dataclass(frozen=True)
class ScoreboardMatch:
    match: "Match"
    team1: ScoreboardSide
    team2: ScoreboardSide


@dataclass(frozen=True)
class FieldScoreboard:
    """Scoreboard state of one field.

    Attributes:
        active: The match in progress, or ``None`` when the field is idle.
        points: The active match's points ordered by stamp.
        set_scores: The active match's ``set number -> (team1, team2)``
            points, ordered by set number.
        previous: Most recently finished match, only computed when idle.
        next: Upcoming match, only computed when idle.
    """

    active: ScoreboardMatch | None
    points: list = field(default_factory=list)
    set_scores: dict[int, tuple[int, int]] = field(default_factory=dict)
    previous: ScoreboardMatch | None = None
    next: ScoreboardMatch | None = None


def set_scores(points) -> dict[int, tuple[int, int]]:
    """Points won by each side per set, ordered by set number.

    Rerolled points count for neither side; points without a set number are
    ignored.
    """
    scores: dict[int, list[int]] = {}
    for point in points:
        if not point.set_number:
            continue
        score = scores.setdefault(point.set_number, [0, 0])
        if point.rerolled:
            continue
        if point.winner == WinnerSide.TEAM1:
            score[0] += 1
        elif point.winner == WinnerSide.TEAM2:
            score[1] += 1
    return {number: (score[0], score[1]) for number, score in sorted(scores.items())}


def _side(tournament, team_id: str | None, initial: str | None) -> ScoreboardSide:
    """Registration pseudonym, else team name, else the slot's initial."""
    from app.services.registration_resolver import team_registration_for_tournament
    from models import Team

    if not team_id:
        return ScoreboardSide(name=initial, shortname=None, photo=None)
    team = Team.query.get(team_id)
    registration = team_registration_for_tournament(tournament, team_id) if tournament else None
    if registration and registration.pseudonym:
        name = registration.pseudonym
    else:
        name = team.name if team else initial
    return ScoreboardSide(
        name=name,
        shortname=registration.shortname if registration and registration.shortname else None,
        photo=team.profile_photo if team and team.profile_photo else None,
    )


def _scoreboard_match(tournament, match) -> ScoreboardMatch:
    return ScoreboardMatch(
        match=match,
        team1=_side(tournament, match.team1, match.team1_initial),
        team2=_side(tournament, match.team2, match.team2_initial),
    )


@dataclass(frozen=True)
class ScoreboardService:
    @staticmethod
    def field_state(tournament_url: str, field_name: str) -> FieldScoreboard:
        """Scoreboard state of the field named *field_name* in *tournament_url*."""
        from models import Match, Point, Tournament

        tournament = Tournament.query.get(tournament_url)
        active = Match.query.filter_by(event=tournament_url, field=field_name, status=MatchStatus.IN_PROGRESS).first()
        if active:
            points = Point.query.filter_by(match=active.uuid).order_by(Point.stamp).all()
            return FieldScoreboard(
                active=_scoreboard_match(tournament, active),
                points=points,
                set_scores=set_scores(points),
            )

        field_matches = (
            Match.query.filter_by(event=tournament_url, field=field_name)
            .order_by(Match.nominal_start_time.asc(), Match.completed_time.asc())
            .all()
        )
        games = [m for m in field_matches if m.schedule_type not in STRUCTURAL_SCHEDULE_TYPES]
        finished = (MatchStatus.COMPLETED, MatchStatus.SKIPPED)
        previous = next(
            (m for m in reversed(games) if m.status in finished and m.completed_time),
            None,
        )
        upcoming = next(
            (
                m
                for m in games
                if m.status in (MatchStatus.NOT_STARTED, MatchStatus.IN_PROGRESS)
                or (m.status in finished and not m.completed_time)
            ),
            None,
        )
        return FieldScoreboard(
            active=None,
            previous=_scoreboard_match(tournament, previous) if previous else None,
            next=_scoreboard_match(tournament, upcoming) if upcoming else None,
        )
