"""``/api/v1/tournaments/<id>/matches`` and live field scoreboards."""

from __future__ import annotations

from flask import jsonify, request
from sqlalchemy import or_

from app.domain.enums import MatchStatus, parse_enum
from app.error_values import Some
from app.serializers.api_v1_serializer import (
    TeamNames,
    match_detail_json,
    match_json,
    scope_of,
    scoreboard_json,
)
from app.services.scoreboard_service import ScoreboardService
from app.utils.oauth_server import require_bearer
from models import Field, Match, Point

from . import bp, can_view_schedule, error, with_tournament


@bp.get("/tournaments/<tournament_id>/matches")
@require_bearer()
@with_tournament
def list_matches(tournament):
    """The schedule with results, by start time. Query: ``field``, ``team``, ``status``.

    403 while the schedule is unpublished, as on the website.
    """
    if not can_view_schedule(tournament):
        return error("Schedule not published", 403)
    status = None
    if status_argument := request.args.get("status"):
        match parse_enum(MatchStatus, status_argument.upper()):
            case Some(parsed):
                status = parsed
            case _:
                return error(f"Unknown status {status_argument!r}", 400)

    query = Match.query.filter_by(event=tournament.url)
    if field := request.args.get("field"):
        query = query.filter(Match.field == field)
    if team := request.args.get("team"):
        query = query.filter(or_(Match.team1 == team, Match.team2 == team))
    matches = [
        m
        for m in query.order_by(Match.nominal_start_time.asc()).all()
        if status is None or m.effective_status == status
    ]

    points_by_match: dict[str, list] = {}
    if matches:
        for point in Point.query.filter(Point.match.in_([m.uuid for m in matches])).all():
            points_by_match.setdefault(point.match, []).append(point)
    teams = TeamNames(scope_of(tournament))
    return jsonify({"matches": [match_json(m, teams, points_by_match.get(m.uuid, [])) for m in matches]})


@bp.get("/tournaments/<tournament_id>/matches/<match_id>")
@require_bearer()
@with_tournament
def get_match(tournament, match_id: str):
    """One match with its referees, published footage, and points."""
    match = Match.query.filter_by(uuid=match_id, event=tournament.url).first()
    if match is None:
        return error("Match not found", 404)
    points = Point.query.filter_by(match=match.uuid).order_by(Point.stamp).all()
    return jsonify({"match": match_detail_json(match, TeamNames(scope_of(tournament)), points)})


@bp.get("/tournaments/<tournament_id>/fields/<path:field_name>/scoreboard")
@require_bearer()
@with_tournament
def field_scoreboard(tournament, field_name: str):
    """Live state of a field: the match in progress with its points, or the previous and next matches."""
    if Field.query.filter_by(event=tournament.url, name=field_name).first() is None:
        return error("Field not found", 404)
    return jsonify(scoreboard_json(ScoreboardService.field_state(tournament.url, field_name)))
