"""``/api/v1/tournaments/<id>/matches/<match_id>/footage``: footage upload for organizers.

Needs a token with the ``footage`` scope whose user is a TO of the
tournament. Shares :class:`~app.services.footage_service.FootageService`
with the SPA's session routes.
"""

from __future__ import annotations

from flask import request

from app.services.footage_service import FootageService
from app.utils.oauth_server import require_bearer

from . import bp, error, json_object_body, result_response, token_actor, with_tournament

FOOTAGE_PATH = "/tournaments/<tournament_id>/matches/<match_id>/footage"


@bp.post(f"{FOOTAGE_PATH}/uploads")
@require_bearer(scope="footage", user_required=True)
@with_tournament
def begin_footage_upload(tournament, match_id: str):
    """JSON ``{camera_name, filename, content_type, total_chunks, anchors}`` -> ``{"upload_id"}``."""
    body = json_object_body()
    if body is None:
        return error("Expected a JSON object body", 400)
    result = FootageService.begin_upload(
        tournament.url,
        match_id,
        **token_actor(),
        camera_name=body.get("camera_name"),
        filename=body.get("filename"),
        content_type=body.get("content_type"),
        total_chunks=body.get("total_chunks"),
        anchors=body.get("anchors"),
    )
    return result_response(result, lambda upload_id: {"upload_id": upload_id})


@bp.put(f"{FOOTAGE_PATH}/uploads/<upload_id>/chunks/<int:index>")
@require_bearer(scope="footage", user_required=True)
@with_tournament
def put_footage_chunk(tournament, match_id: str, upload_id: str, index: int):
    """Raw request body = the chunk's bytes -> ``{"received": index}``."""
    result = FootageService.write_chunk(
        tournament.url,
        match_id,
        **token_actor(),
        upload_id=upload_id,
        chunk_index=index,
        stream=request.stream,
    )
    return result_response(result, lambda received: {"received": received})


@bp.post(f"{FOOTAGE_PATH}/uploads/<upload_id>/complete")
@require_bearer(scope="footage", user_required=True)
@with_tournament
def complete_footage_upload(tournament, match_id: str, upload_id: str):
    """Assemble the chunks and start publishing to YouTube -> ``{"camera_uuid"}``."""
    result = FootageService.complete_upload(tournament.url, match_id, **token_actor(), upload_id=upload_id)
    return result_response(result, lambda camera_uuid: {"camera_uuid": camera_uuid})


@bp.post(f"{FOOTAGE_PATH}/links")
@require_bearer(scope="footage", user_required=True)
@with_tournament
def link_footage(tournament, match_id: str):
    """JSON ``{youtube_link, camera_name, anchors}`` -> ``{"camera_uuid"}``."""
    body = json_object_body()
    if body is None:
        return error("Expected a JSON object body", 400)
    result = FootageService.attach_youtube_link(
        tournament.url,
        match_id,
        **token_actor(),
        youtube_link=body.get("youtube_link"),
        camera_name=body.get("camera_name"),
        anchors=body.get("anchors"),
    )
    return result_response(result, lambda camera_uuid: {"camera_uuid": camera_uuid})
