"""Integration tests for the public footage endpoints (``/api/v1/.../footage``)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.domain.enums import MatchStatus, ScheduleType
from app.services.dual_write import get_camera_timepoint_arrays
from models import TO, Camera, Field, Match, Player, Point, Tournament, db
from tests.utils import issue_access_token, make_registrable_config

pytestmark = pytest.mark.integration

YOUTUBE_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.fixture
def footage_match(test_db):
    """A published tournament with a TO, a bystander player, and a completed match with points."""
    tournament = Tournament(
        url="footage-cup",
        name="Footage Cup",
        start_date=datetime.now(timezone.utc),
        published=True,
        registrable_config_id=make_registrable_config().id,
    )
    db.session.add(tournament)
    db.session.flush()
    db.session.add(Field(event=tournament.url, name="Field 1"))
    organizer = Player(id="footage-to", name="Footage TO", pw_hash="x")
    bystander = Player(id="bystander", name="Bystander", pw_hash="x")
    db.session.add_all([organizer, bystander])
    db.session.add(TO(user_id=organizer.id, user_type="player", event=tournament.url))
    match = Match(
        name="Game 1",
        event=tournament.url,
        field="Field 1",
        schedule_type=ScheduleType.STATIC,
        status=MatchStatus.COMPLETED,
    )
    db.session.add(match)
    db.session.flush()
    base = datetime(2026, 1, 1)
    db.session.add(Point(match=match.uuid, winner="TEAM1", stamp=base))
    db.session.add(Point(match=match.uuid, winner="TEAM2", stamp=base + timedelta(seconds=30)))
    db.session.commit()
    return {
        "footage_url": f"/api/v1/tournaments/footage-cup/matches/{match.uuid}/footage",
        "organizer": organizer,
        "bystander": bystander,
    }


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_chunked_upload_happy_path(client, footage_match):
    headers = _bearer(issue_access_token(footage_match["organizer"], scope="footage"))
    uploads_url = f"{footage_match['footage_url']}/uploads"
    with (
        patch("app.utils.user_uploads.upload_camera_to_youtube") as upload_to_youtube,
        patch("app.utils.user_uploads.threading.Thread") as thread,
    ):
        thread.side_effect = lambda target, daemon=False: type("T", (), {"start": lambda self: target()})()
        begun = client.post(
            uploads_url,
            headers=headers,
            json={
                "camera_name": "Recorder",
                "filename": "game.mp4",
                "content_type": "video/mp4",
                "total_chunks": 2,
                "anchors": [{"point_index": 1, "video_offset": 4.5}],
            },
        )
        assert begun.status_code == 200
        upload_id = begun.get_json()["upload_id"]
        for index, data in enumerate((b"first-half", b"second-half")):
            chunk = client.put(
                f"{uploads_url}/{upload_id}/chunks/{index}",
                headers=headers,
                data=data,
                content_type="application/octet-stream",
            )
            assert chunk.status_code == 200
            assert chunk.get_json() == {"received": index}
        completed = client.post(f"{uploads_url}/{upload_id}/complete", headers=headers)
    assert completed.status_code == 200
    camera = Camera.query.filter_by(uuid=completed.get_json()["camera_uuid"]).one()
    assert (camera.name, camera.status, camera.source_type) == ("Recorder", "UPLOADING", "user_upload")
    assert get_camera_timepoint_arrays(camera)[1] == [4.5]
    upload_to_youtube.assert_called_once()


def test_complete_with_missing_chunks_fails(client, footage_match):
    headers = _bearer(issue_access_token(footage_match["organizer"], scope="footage"))
    uploads_url = f"{footage_match['footage_url']}/uploads"
    begun = client.post(
        uploads_url,
        headers=headers,
        json={"camera_name": "Cam", "filename": "game.mp4", "content_type": "video/mp4", "total_chunks": 2},
    )
    upload_id = begun.get_json()["upload_id"]
    completed = client.post(f"{uploads_url}/{upload_id}/complete", headers=headers)
    assert completed.status_code == 400
    assert "error" in completed.get_json()


def test_youtube_link(client, footage_match):
    response = client.post(
        f"{footage_match['footage_url']}/links",
        headers=_bearer(issue_access_token(footage_match["organizer"], scope="footage")),
        json={
            "youtube_link": "https://youtu.be/dQw4w9WgXcQ",
            "camera_name": "Phone",
            "anchors": [{"world_time": "2026-01-01T00:00:00Z", "video_offset": 1.0}],
        },
    )
    assert response.status_code == 200
    camera = Camera.query.filter_by(uuid=response.get_json()["camera_uuid"]).one()
    assert (camera.status, camera.link) == ("SUCCESS", YOUTUBE_URL)
    assert get_camera_timepoint_arrays(camera)[1] == [1.0]


@pytest.mark.parametrize("who", ["organizer without footage scope", "non-organizer", "client credentials"])
def test_footage_requires_organizer_with_footage_scope(client, footage_match, who):
    token = {
        "organizer without footage scope": lambda: issue_access_token(footage_match["organizer"], scope="injuries"),
        "non-organizer": lambda: issue_access_token(footage_match["bystander"], scope="footage"),
        "client credentials": lambda: issue_access_token(scope="footage"),
    }[who]()
    footage_url = footage_match["footage_url"]
    begun = client.post(
        f"{footage_url}/uploads",
        headers=_bearer(token),
        json={"camera_name": "Cam", "filename": "game.mp4", "content_type": "video/mp4", "total_chunks": 1},
    )
    assert begun.status_code == 403
    assert "error" in begun.get_json()
    linked = client.post(
        f"{footage_url}/links",
        headers=_bearer(token),
        json={"youtube_link": YOUTUBE_URL, "camera_name": "Cam"},
    )
    assert linked.status_code == 403
    assert Camera.query.count() == 0


def test_completion_is_bound_to_the_uploader(client, footage_match, test_db):
    second_organizer = Player(id="second-to", name="Second TO", pw_hash="x")
    db.session.add(second_organizer)
    db.session.add(TO(user_id=second_organizer.id, user_type="player", event="footage-cup"))
    db.session.commit()
    uploads_url = f"{footage_match['footage_url']}/uploads"
    begun = client.post(
        uploads_url,
        headers=_bearer(issue_access_token(footage_match["organizer"], scope="footage")),
        json={"camera_name": "Cam", "filename": "game.mp4", "content_type": "video/mp4", "total_chunks": 1},
    )
    upload_id = begun.get_json()["upload_id"]
    other_headers = _bearer(issue_access_token(second_organizer, scope="footage"))
    assert client.put(f"{uploads_url}/{upload_id}/chunks/0", headers=other_headers, data=b"x").status_code == 200
    completed = client.post(f"{uploads_url}/{upload_id}/complete", headers=other_headers)
    assert completed.status_code == 403
    assert completed.get_json() == {"error": "You cannot complete another user's upload"}
