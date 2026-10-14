"""Scoreboard overlay frames for compositing over recorded match footage.

Part of the ``tournaments`` blueprint. Uses the same Blueprint object
defined in :mod:`app.routes.tournaments.__init__`.
"""

from __future__ import annotations

import base64

from flask import request

from app.error_values import Err, Ok
from app.services.scoreboard_service import ScoreboardService
from app.utils.datetime_helpers import to_iso_z
from app.utils.helpers import check_tournament_access
from app.utils.responses import json_error, json_success
from app.utils.result_helpers import public_error_message
from app.utils.scoreboard_render import render_scoreboard_frames, validate_overlay_size

from . import bp


@bp.route("/tournaments/<tournament_url>/matches/<match_id>/scoreboard-overlay", methods=["GET"])
def scoreboard_overlay(tournament_url: str, match_id: str):
    """Rendered scoreboard images for a match, each with the time it takes effect.

    ``GET /_api/tournaments/<tournament_url>/matches/<match_id>/scoreboard-overlay?width=W&height=H``

    Frames are transparent ``W`` x ``H`` PNGs of the live OBS scoreboard,
    one per distinct scoreboard state derived from the match's points.
    Visible to anyone who can view the tournament.

    Returns:
        ``{"success": true, "width": W, "height": H, "frames": [{"effective_at": "<ISO-8601 Z>",
        "png": "<base64>"}, ...]}``; 400 for a bad size or an unstarted match, 404 for an
        unknown/hidden tournament or match, 503 when the renderer is unavailable.
    """
    match validate_overlay_size(request.args.get("width", type=int), request.args.get("height", type=int)):
        case Err(err):
            return json_error(public_error_message(err), err.status_code)
        case Ok((width, height)):
            pass

    has_access, tournament = check_tournament_access(tournament_url)
    if not has_access or not tournament:
        return json_error("Not found", 404)

    match ScoreboardService.match_timeline(tournament, match_id):
        case Err(err):
            return json_error(public_error_message(err), err.status_code)
        case Ok(timeline):
            pass

    match render_scoreboard_frames([entry.state for entry in timeline], width, height):
        case Err(err):
            return json_error(public_error_message(err), err.status_code)
        case Ok(pngs):
            pass

    return json_success(
        {
            "width": width,
            "height": height,
            "frames": [
                {"effective_at": to_iso_z(entry.effective_at).unwrap(), "png": base64.b64encode(png).decode("ascii")}
                for entry, png in zip(timeline, pngs)
            ],
        }
    )
