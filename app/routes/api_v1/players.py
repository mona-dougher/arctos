"""``/api/v1/players``: player directory, profiles, and injuries."""

from __future__ import annotations

from flask import g, jsonify, request

from app.domain.enums import UserType
from app.serializers.api_v1_serializer import (
    injury_json,
    player_profile_json,
    player_registrations_json,
    player_summary_json,
)
from app.utils.oauth_server import require_bearer
from models import Injury, Player

from . import bp, error, paginated, token_has_scope


@bp.get("/players")
@require_bearer()
def list_players():
    """Players by name, 50 per page. Query: ``search`` (name or id), ``page``."""
    query = Player.query
    if search := request.args.get("search", "").strip():
        query = query.filter(Player.name.contains(search) | Player.id.contains(search))
    players, page = paginated(query, Player.name.asc())
    return jsonify({"players": [player_summary_json(p) for p in players]} | page)


@bp.get("/players/<player_id>")
@require_bearer()
def get_player(player_id: str):
    player = Player.query.get(player_id)
    if player is None:
        return error("Player not found", 404)
    return jsonify({"player": player_profile_json(player) | {"registrations": player_registrations_json(player.id)}})


@bp.get("/players/<player_id>/injuries")
@require_bearer()
def list_player_injuries(player_id: str):
    """Public injuries; all of them when the token acts for this player and has the ``injuries`` scope."""
    player = Player.query.get(player_id)
    if player is None:
        return error("Player not found", 404)
    is_own = (
        g.oauth_user is not None
        and g.oauth_token.user_type == UserType.PLAYER
        and g.oauth_user.id == player.id
        and token_has_scope("injuries")
    )
    query = Injury.query.filter_by(player=player.id)
    if not is_own:
        query = query.filter_by(show=True)
    injuries = query.order_by(Injury.stamp.desc()).all()
    return jsonify({"injuries": [injury_json(injury) for injury in injuries]})
