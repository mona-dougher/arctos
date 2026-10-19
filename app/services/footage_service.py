"""Match footage: attach a YouTube link or a chunked video upload to a match.

Creates match-scoped Camera rows with optional camera_timepoints anchors
that the match page's YouTube-iframe display path reads for jump-to-point.
Uploaded files are published to YouTube in the background.

Every workflow takes an explicit actor (user id + type) who must be a TO of
the tournament, so the session routes in
:mod:`app.routes.tournaments.footage` and the bearer-token routes of the
public API share it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from os import path
from typing import BinaryIO

from app.error_values import Err, Ok, Result, allow_Q
from app.exceptions import ArctosError, NotFoundError, UnauthorizedError, ValidationError

UPLOAD_ID_RE = re.compile(r"[A-Za-z0-9_-]{6,80}")

MAX_UPLOAD_CHUNKS = 2048
MAX_CHUNK_BYTES = 16 * 1024 * 1024
MAX_UPLOAD_BYTES = 32 * 1024 * 1024 * 1024
INCOMING_TTL_SECONDS = 24 * 60 * 60
ALLOWED_EXTENSIONS = {".mp4", ".webm"}
ALLOWED_CONTENT_TYPES = {"video/mp4", "video/webm"}
COPY_BUFFER_BYTES = 1024 * 1024


def _videos_root() -> str:
    from flask import current_app

    return path.realpath(path.join(current_app.root_path, "..", "static", "uploads", "videos"))


def _ensure_under_videos_root(candidate: str) -> str:
    root = _videos_root()
    resolved = path.realpath(candidate)
    if resolved != root and not resolved.startswith(root + os.sep):
        raise ValueError("path escapes uploads root")
    return resolved


def _incoming_parent(tournament_url: str, field_id: int | str) -> str:
    return _ensure_under_videos_root(
        path.join(_videos_root(), tournament_url, str(field_id), "user_uploads", "_incoming")
    )


def _incoming_dir(tournament_url: str, field_id: int | str, upload_id: str) -> str:
    return _ensure_under_videos_root(path.join(_incoming_parent(tournament_url, field_id), upload_id))


def _cleanup_stale_incoming(tournament_url: str, field_id: int | str) -> None:
    try:
        parent = _incoming_parent(tournament_url, field_id)
    except ValueError:
        return
    if not path.isdir(parent):
        return
    cutoff = time.time() - INCOMING_TTL_SECONDS
    for name in os.listdir(parent):
        candidate = path.join(parent, name)
        try:
            if not path.isdir(candidate):
                continue
            if path.getmtime(candidate) < cutoff:
                shutil.rmtree(candidate, ignore_errors=True)
        except OSError:
            continue


def _normalize_upload_filename(filename: str, content_type: str) -> tuple[str, str, str]:
    """Return ``(safe_filename, extension, content_type)`` or raise ``ValueError``."""
    base = path.basename((filename or "").strip()) or "source.mp4"
    base = base.replace("\x00", "")
    ext = path.splitext(base)[1].lower()
    ctype = (content_type or "").strip().lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("filename must end in .mp4 or .webm")
    if ctype and ctype not in ALLOWED_CONTENT_TYPES:
        raise ValueError("content_type must be video/mp4 or video/webm")
    if not ctype:
        ctype = "video/mp4" if ext == ".mp4" else "video/webm"
    elif (ext == ".mp4" and ctype != "video/mp4") or (ext == ".webm" and ctype != "video/webm"):
        raise ValueError("content_type does not match filename extension")

    stem = path.splitext(base)[0] or "source"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem)[:80] or "source"
    return f"{stem}{ext}", ext, ctype


def _require_organizer(tournament_url: str, actor_user_id: str, actor_user_type: str) -> Result[None, ArctosError]:
    from app.services._common import resolve_actor
    from app.services.permission_service import PermissionService

    actor = resolve_actor(actor_user_id, actor_user_type)
    if not PermissionService.is_tournament_organizer(tournament_url, actor):
        return Err(UnauthorizedError("Only tournament organizers can upload footage"))
    return Ok(None)


def _resolve_match_field(tournament_url: str, match_id: str) -> Result[tuple, ArctosError]:
    from models import Field, Match

    match = Match.query.filter_by(uuid=match_id, event=tournament_url).first()
    if not match:
        return Err(NotFoundError("Match not found"))
    if not match.field:
        return Err(ValidationError("Match has no field"))
    field = Field.query.filter_by(event=tournament_url, name=match.field).first()
    if not field:
        return Err(NotFoundError("Match field not found"))
    return Ok((match, field))


def _validated_upload_id(upload_id: str) -> Result[str, ArctosError]:
    upload_id = (upload_id or "").strip()
    if not upload_id or not UPLOAD_ID_RE.fullmatch(upload_id):
        return Err(ValidationError("Invalid upload_id"))
    return Ok(upload_id)


def _pending_upload(tournament_url: str, field_id: int, upload_id: str) -> Result[tuple[str, dict], ArctosError]:
    """Return the ``(incoming directory, metadata)`` of an upload begun with :meth:`FootageService.begin_upload`."""
    try:
        incoming = _incoming_dir(tournament_url, field_id, upload_id)
    except ValueError:
        return Err(ValidationError("Invalid upload path"))
    meta_path = path.join(incoming, "meta.json")
    if not path.exists(meta_path):
        return Err(NotFoundError("Upload not found"))
    with open(meta_path) as handle:
        return Ok((incoming, json.load(handle)))


def _chunk_path(incoming: str, index: int) -> str:
    return path.join(incoming, f"chunk_{index:06d}.part")


@dataclass(frozen=True)
class FootageService:
    @staticmethod
    @allow_Q
    def attach_youtube_link(
        tournament_url: str,
        match_id: str,
        *,
        actor_user_id: str,
        actor_user_type: str,
        youtube_link: str,
        camera_name: str,
        anchors,
    ) -> Result[str, ArctosError]:
        """Attach a YouTube video as footage for a match; returns the camera uuid."""
        from app.services.dual_write import set_camera_timepoints
        from app.utils.user_uploads import normalize_anchors
        from app.utils.youtube_upload import canonical_youtube_watch_url
        from models import Camera, db

        _require_organizer(tournament_url, actor_user_id, actor_user_type).Q()
        _, field = _resolve_match_field(tournament_url, match_id).Q()

        youtube_link = (youtube_link or "").strip()
        camera_name = (camera_name or "").strip()
        if not youtube_link:
            return Err(ValidationError("youtube_link is required"))
        if not camera_name:
            return Err(ValidationError("camera_name is required"))
        try:
            youtube_link = canonical_youtube_watch_url(youtube_link)
            worlds, videos = normalize_anchors(match_id, tournament_url, anchors)
        except ValueError as exc:
            return Err(ValidationError(str(exc)))

        camera = Camera(
            match_uuid=match_id,
            event=tournament_url,
            field=field.id,
            name=camera_name[:200],
            source_type="user_upload",
            uploaded_by_user_id=str(actor_user_id),
            uploaded_by_user_type=actor_user_type,
            status="SUCCESS",
            link=youtube_link,
        )
        db.session.add(camera)
        db.session.flush()
        if worlds:
            set_camera_timepoints(camera, worlds, videos)
        db.session.commit()
        return Ok(camera.uuid)

    @staticmethod
    @allow_Q
    def begin_upload(
        tournament_url: str,
        match_id: str,
        *,
        actor_user_id: str,
        actor_user_type: str,
        camera_name: str,
        filename: str,
        content_type: str,
        total_chunks,
        anchors,
    ) -> Result[str, ArctosError]:
        """Begin a chunked file upload; returns the upload id chunks are sent to."""
        from app.utils.user_uploads import normalize_anchors

        _require_organizer(tournament_url, actor_user_id, actor_user_type).Q()
        _, field = _resolve_match_field(tournament_url, match_id).Q()

        camera_name = (camera_name or "").strip()
        try:
            total_chunks = int(total_chunks)
        except (TypeError, ValueError):
            return Err(ValidationError("total_chunks must be an integer"))
        if total_chunks <= 0:
            return Err(ValidationError("total_chunks must be > 0"))
        if total_chunks > MAX_UPLOAD_CHUNKS:
            return Err(ValidationError(f"total_chunks must be <= {MAX_UPLOAD_CHUNKS}"))
        if not camera_name:
            return Err(ValidationError("camera_name is required"))
        try:
            safe_filename, _, normalized_content_type = _normalize_upload_filename(
                (filename or "source.mp4").strip(), (content_type or "").strip()
            )
            normalize_anchors(match_id, tournament_url, anchors)
        except ValueError as exc:
            return Err(ValidationError(str(exc)))

        _cleanup_stale_incoming(tournament_url, field.id)

        upload_id = uuid.uuid4().hex
        try:
            incoming = _incoming_dir(tournament_url, field.id, upload_id)
        except ValueError:
            return Err(ValidationError("Invalid upload path"))
        os.makedirs(incoming, exist_ok=True)
        meta = {
            "upload_id": upload_id,
            "match_uuid": match_id,
            "field_id": field.id,
            "camera_name": camera_name,
            "filename": safe_filename,
            "content_type": normalized_content_type,
            "total_chunks": total_chunks,
            "anchors": anchors,
            "uploaded_by_user_id": str(actor_user_id),
            "uploaded_by_user_type": actor_user_type,
            "created_at": time.time(),
        }
        with open(path.join(incoming, "meta.json"), "w") as handle:
            json.dump(meta, handle)
        return Ok(upload_id)

    @staticmethod
    @allow_Q
    def write_chunk(
        tournament_url: str,
        match_id: str,
        *,
        actor_user_id: str,
        actor_user_type: str,
        upload_id: str,
        chunk_index: int | str,
        stream: BinaryIO | None,
    ) -> Result[int, ArctosError]:
        """Store chunk *chunk_index* of an upload, read from *stream*; returns the index.

        Each chunk is capped at :data:`MAX_CHUNK_BYTES` and the whole upload
        at :data:`MAX_UPLOAD_BYTES`. Re-sending a chunk replaces it.
        """
        _require_organizer(tournament_url, actor_user_id, actor_user_type).Q()
        upload_id = _validated_upload_id(upload_id).Q()
        if stream is None:
            return Err(ValidationError("chunk is required"))
        _, field = _resolve_match_field(tournament_url, match_id).Q()
        incoming, meta = _pending_upload(tournament_url, field.id, upload_id).Q()

        try:
            chunk_index = int(chunk_index)
        except ValueError:
            return Err(ValidationError("chunk_index must be an integer"))
        if chunk_index < 0 or chunk_index >= int(meta["total_chunks"]):
            return Err(ValidationError("chunk_index out of range"))

        part_path = _chunk_path(incoming, chunk_index)
        total_existing = 0
        for name in os.listdir(incoming):
            if name.startswith("chunk_") and name.endswith(".part") and name != path.basename(part_path):
                try:
                    total_existing += path.getsize(path.join(incoming, name))
                except OSError:
                    pass

        def discard_part(message: str) -> Result[int, ArctosError]:
            try:
                os.remove(part_path)
            except OSError:
                pass
            return Err(ValidationError(message))

        written = 0
        with open(part_path, "wb") as out:
            while True:
                buffer = stream.read(COPY_BUFFER_BYTES)
                if not buffer:
                    break
                written += len(buffer)
                if written > MAX_CHUNK_BYTES:
                    out.close()
                    return discard_part(f"chunk exceeds {MAX_CHUNK_BYTES} bytes")
                if total_existing + written > MAX_UPLOAD_BYTES:
                    out.close()
                    return discard_part(f"upload exceeds {MAX_UPLOAD_BYTES} bytes")
                out.write(buffer)
        return Ok(chunk_index)

    @staticmethod
    @allow_Q
    def complete_upload(
        tournament_url: str,
        match_id: str,
        *,
        actor_user_id: str,
        actor_user_type: str,
        upload_id: str,
    ) -> Result[str, ArctosError]:
        """Assemble the chunks, create the Camera row, and start the YouTube upload; returns the camera uuid.

        Only the actor who began the upload may complete it.
        """
        from flask import current_app

        from app.utils.user_uploads import create_direct_user_upload_camera

        _require_organizer(tournament_url, actor_user_id, actor_user_type).Q()
        upload_id = _validated_upload_id(upload_id).Q()
        _, field = _resolve_match_field(tournament_url, match_id).Q()
        incoming, meta = _pending_upload(tournament_url, field.id, upload_id).Q()

        if str(meta.get("uploaded_by_user_id")) != str(actor_user_id):
            return Err(UnauthorizedError("You cannot complete another user's upload"))

        total_chunks = int(meta["total_chunks"])
        if total_chunks > MAX_UPLOAD_CHUNKS:
            return Err(ValidationError("Upload exceeds chunk limit"))

        ext = path.splitext(path.basename(meta.get("filename") or "source.mp4"))[1].lower() or ".mp4"
        if ext not in ALLOWED_EXTENSIONS:
            return Err(ValidationError("Unsupported media type"))
        source_path = path.join(incoming, f"source{ext}")
        assembled = 0
        with open(source_path, "wb") as out:
            for index in range(total_chunks):
                part = _chunk_path(incoming, index)
                if not path.exists(part):
                    return Err(ValidationError(f"Missing chunk {index}"))
                with open(part, "rb") as chunk:
                    while True:
                        buffer = chunk.read(COPY_BUFFER_BYTES)
                        if not buffer:
                            break
                        assembled += len(buffer)
                        if assembled > MAX_UPLOAD_BYTES:
                            return Err(ValidationError(f"upload exceeds {MAX_UPLOAD_BYTES} bytes"))
                        out.write(buffer)

        try:
            camera_uuid = create_direct_user_upload_camera(
                current_app.logger,
                current_app._get_current_object(),  # type: ignore[attr-defined]
                tournament_url=tournament_url,
                match_uuid=match_id,
                camera_name=meta.get("camera_name") or "",
                upload_key=upload_id,
                saved_abs_path=source_path,
                uploader_user_id=str(actor_user_id),
                uploader_user_type=actor_user_type,
                anchors=meta.get("anchors"),
            )
        except ValueError as exc:
            return Err(ValidationError(str(exc)))

        for index in range(total_chunks):
            part = _chunk_path(incoming, index)
            if path.exists(part):
                os.remove(part)
        return Ok(camera_uuid)
