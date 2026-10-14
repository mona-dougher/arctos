"""Footage API: TO-authenticated video upload (YouTube link or chunked file).

Session-authenticated wrappers around
:class:`~app.services.footage_service.FootageService`, plus the footage
list/delete endpoints behind the Manage Footage page.
"""

from flask import request, jsonify, current_app
from flask_login import current_user

import os
from os import path

from models import Match, Field, Camera, db
from app.error_values import Err, Ok
from app.services._common import current_user_type
from app.services.dual_write import get_camera_timepoint_arrays, set_camera_timepoints
from app.services.footage_service import FootageService
from app.utils.decorators import require_tournament_organizer
from app.utils.result_helpers import public_error_message

from . import bp


def _footage_response(result, ok_to_payload):
    match result:
        case Ok(value):
            return jsonify(ok_to_payload(value))
        case Err(err):
            return jsonify({"error": public_error_message(err)}), err.status_code


def _actor() -> dict:
    return {"actor_user_id": str(current_user.id), "actor_user_type": current_user_type()}


@bp.route("/tournaments/<tournament_url>/matches/<match_id>/footage/link", methods=["POST"])
@require_tournament_organizer()
def footage_link(tournament_url: str, match_id: str):
    """Attach a YouTube link as footage for a match."""
    payload = request.get_json(silent=True) or {}
    result = FootageService.attach_youtube_link(
        tournament_url,
        match_id,
        **_actor(),
        youtube_link=payload.get("youtube_link"),
        camera_name=payload.get("camera_name"),
        anchors=payload.get("anchors"),
    )
    return _footage_response(result, lambda camera_uuid: {"success": True, "camera_uuid": camera_uuid})


@bp.route("/tournaments/<tournament_url>/matches/<match_id>/footage/upload/init", methods=["POST"])
@require_tournament_organizer()
def footage_upload_init(tournament_url: str, match_id: str):
    """Begin a chunked file upload; returns an upload_id."""
    payload = request.get_json(silent=True) or {}
    result = FootageService.begin_upload(
        tournament_url,
        match_id,
        **_actor(),
        camera_name=payload.get("camera_name"),
        filename=payload.get("filename"),
        content_type=payload.get("content_type"),
        total_chunks=payload.get("total_chunks"),
        anchors=payload.get("anchors"),
    )
    return _footage_response(result, lambda upload_id: {"upload_id": upload_id})


@bp.route("/tournaments/<tournament_url>/matches/<match_id>/footage/upload/chunk", methods=["POST"])
@require_tournament_organizer()
def footage_upload_chunk(tournament_url: str, match_id: str):
    """Receive one chunk of a chunked file upload."""
    chunk_file = request.files.get("chunk")
    result = FootageService.write_chunk(
        tournament_url,
        match_id,
        **_actor(),
        upload_id=request.form.get("upload_id"),
        chunk_index=(request.form.get("chunk_index") or "").strip(),
        stream=chunk_file.stream if chunk_file is not None else None,
    )
    return _footage_response(result, lambda _: {"success": True})


@bp.route("/tournaments/<tournament_url>/matches/<match_id>/footage/upload/complete", methods=["POST"])
@require_tournament_organizer()
def footage_upload_complete(tournament_url: str, match_id: str):
    """Assemble chunks, create the Camera row, and start the YouTube upload."""
    payload = request.get_json(silent=True) or {}
    result = FootageService.complete_upload(tournament_url, match_id, **_actor(), upload_id=payload.get("upload_id"))
    return _footage_response(result, lambda camera_uuid: {"success": True, "camera_uuid": camera_uuid})


@bp.route("/tournaments/<tournament_url>/matches/<match_id>/footage", methods=["GET"])
@require_tournament_organizer()
def list_match_footage(tournament_url: str, match_id: str):
    """List cameras attached to a match."""
    cams = Camera.query.filter_by(match_uuid=match_id, event=tournament_url).order_by(Camera.name.asc()).all()
    return jsonify(
        {
            "cameras": [
                {
                    "uuid": c.uuid,
                    "name": c.name,
                    "status": c.status,
                    "link": c.link,
                    "source_type": c.source_type,
                }
                for c in cams
            ]
        }
    )


@bp.route("/tournaments/<tournament_url>/matches/<match_id>/footage/<camera_uuid>", methods=["DELETE"])
@require_tournament_organizer()
def delete_match_footage(tournament_url: str, match_id: str, camera_uuid: str):
    """Delete a camera (and its timepoints + local file)."""
    cam = Camera.query.filter_by(uuid=camera_uuid, event=tournament_url, match_uuid=match_id).first()
    if not cam:
        return jsonify({"error": "Camera not found"}), 404
    if cam.file:
        try:
            abs_fp = path.join(current_app.root_path, "..", cam.file)
            if os.path.exists(abs_fp):
                os.remove(abs_fp)
        except OSError:
            pass
    set_camera_timepoints(cam, [], [])
    db.session.delete(cam)
    db.session.commit()
    return jsonify({"success": True})


@bp.route("/tournaments/<tournament_url>/footage", methods=["GET"])
@require_tournament_organizer()
def list_event_footage(tournament_url: str):
    """List all cameras for an event (backs the Manage Footage page)."""
    cams = Camera.query.filter_by(event=tournament_url).order_by(Camera.match_uuid.asc(), Camera.name.asc()).all()
    rows = []
    for cam in cams:
        match_obj = Match.query.filter_by(uuid=cam.match_uuid).first()
        field_obj = Field.query.filter_by(id=cam.field).first()
        worlds, _ = get_camera_timepoint_arrays(cam)
        world_start = str(worlds[0]) if worlds and worlds[0] is not None else None
        uploader = None
        if cam.uploaded_by_user_type and cam.uploaded_by_user_id:
            uploader = f"{cam.uploaded_by_user_type}:{cam.uploaded_by_user_id}"
        elif cam.uploaded_by_user_id:
            uploader = str(cam.uploaded_by_user_id)
        rows.append(
            {
                "uuid": cam.uuid,
                "match_uuid": cam.match_uuid,
                "match_name": match_obj.name if match_obj else cam.match_uuid,
                "field_name": field_obj.name if field_obj else str(cam.field),
                "camera_name": cam.name,
                "status": cam.status,
                "user": uploader,
                "world_start_timestamp": world_start,
                "link": cam.link,
            }
        )
    return jsonify({"cameras": rows})
