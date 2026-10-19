"""``/api/v1/leagues``: leagues, their tournaments, rosters, and standings."""

from __future__ import annotations

from flask import g, jsonify, request
from sqlalchemy import or_

from app.domain.enums import MatchStatus
from app.serializers.api_v1_serializer import (
    league_json,
    scope_players_json,
    scope_teams_json,
    standings_json,
    tournament_json,
)
from app.services._common import Scope
from app.services.permission_service import PermissionService
from app.services.team_stats_service import compute_team_stats
from app.utils.oauth_server import require_bearer
from models import League, Match, Tournament

from . import bp, can_view_tournament, flag_argument, sees_unpublished_organized, with_league


def _visible_tournaments(league) -> list:
    tournaments = Tournament.query.filter_by(league_id=league.url).order_by(Tournament.start_date.asc()).all()
    return [t for t in tournaments if can_view_tournament(t)]


@bp.get("/leagues")
@require_bearer()
def list_leagues():
    visible = League.published.is_(True)
    if sees_unpublished_organized():
        _, league_urls = PermissionService.organized_scopes(g.oauth_user)
        visible = or_(visible, League.url.in_(league_urls))
    leagues = League.query.filter(visible).order_by(League.name.asc()).all()
    return jsonify({"leagues": [league_json(league) for league in leagues]})


@bp.get("/leagues/<league_id>")
@require_bearer()
@with_league
def get_league(league):
    return jsonify(
        {
            "league": league_json(league),
            "tournaments": [tournament_json(t) for t in _visible_tournaments(league)],
        }
    )


@bp.get("/leagues/<league_id>/teams")
@require_bearer()
@with_league
def list_league_teams(league):
    return jsonify({"teams": scope_teams_json(Scope.league(league.url))})


@bp.get("/leagues/<league_id>/players")
@require_bearer()
@with_league
def list_league_players(league):
    """Query: ``team`` for one team's roster."""
    return jsonify({"players": scope_players_json(Scope.league(league.url), team_id=request.args.get("team"))})


@bp.get("/leagues/<league_id>/results")
@require_bearer()
@with_league
def league_results(league):
    """Standings across the league's visible tournaments. Query: ``include_ribbon``."""
    tournaments = _visible_tournaments(league)
    if not tournaments:
        return jsonify({"standings": []})
    matches = Match.query.filter(
        Match.event.in_([t.url for t in tournaments]),
        Match.status.in_([MatchStatus.COMPLETED, MatchStatus.SKIPPED]),
    ).all()
    team_stats = compute_team_stats(matches, tournaments[0], include_ribbon=flag_argument("include_ribbon"))
    return jsonify({"standings": standings_json(team_stats)})
