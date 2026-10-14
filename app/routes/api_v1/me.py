"""``/api/v1/me``: the user an access token acts for."""

from __future__ import annotations

from flask import g, jsonify

from app.serializers.api_v1_serializer import user_json
from app.utils.oauth_server import require_bearer

from . import bp


@bp.get("/me")
@require_bearer(user_required=True)
def me():
    """``{"id", "name", "type"}`` of the token's user; 403 for client-credentials tokens."""
    return jsonify(user_json(g.oauth_user, g.oauth_token.user_type))
