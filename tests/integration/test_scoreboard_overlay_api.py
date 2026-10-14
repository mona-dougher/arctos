"""Integration tests for the scoreboard overlay endpoint and the live scoreboard state it shares code with."""

import base64
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.enums import MatchStatus, ScheduleType
from app.error_values import Err, Ok
from app.exceptions import ArctosError
from models import Match, Point, Team, TeamRegistration, Tournament, db
from tests.utils import make_registrable_config

MATCH_START = datetime(2026, 1, 1, 12, 0, 0)


@pytest.fixture
def overlay_match(test_db, tournament):
    """An in-progress SETS match on Field 1 with one scored point and one ongoing point."""
    db.session.add(Team(id="alpha", name="Alpha", pw_hash="x"))
    db.session.add(Team(id="beta", name="Beta", pw_hash="x", profile_photo="uploads/beta.png"))
    db.session.flush()
    db.session.add(
        TeamRegistration(
            event=tournament.url, team="alpha", pseudonym="Alpha Pseudo", shortname="ALP", status="CONFIRMED"
        )
    )
    match = Match(
        name="Game 1",
        event=tournament.url,
        field="Field 1",
        team1="alpha",
        team2="beta",
        schedule_type=ScheduleType.STATIC,
        status=MatchStatus.IN_PROGRESS,
        set_type="SETS",
        started_at=MATCH_START,
    )
    db.session.add(match)
    db.session.flush()
    db.session.add(
        Point(
            match=match.uuid,
            winner="TEAM1",
            stamp=MATCH_START + timedelta(seconds=10),
            end_stamp=MATCH_START + timedelta(seconds=20),
        )
    )
    db.session.add(Point(match=match.uuid, stamp=MATCH_START + timedelta(seconds=30)))
    db.session.commit()
    return match


def overlay_url(tournament_url, match_id, query="width=1280&height=720"):
    return f"/_api/tournaments/{tournament_url}/matches/{match_id}/scoreboard-overlay?{query}"


@pytest.fixture
def fake_renderer(monkeypatch):
    """Replace the browser renderer; records the states it was asked to draw."""
    calls = []

    def render(states, width, height):
        calls.append({"states": states, "width": width, "height": height})
        return Ok([f"png-{index}".encode() for index in range(len(states))])

    monkeypatch.setattr("app.routes.tournaments.scoreboard_overlay.render_scoreboard_frames", render)
    return calls


@pytest.mark.integration
@pytest.mark.parametrize(
    "query",
    [
        "",
        "width=1280",
        "width=abc&height=720",
        "width=0&height=720",
        "width=3841&height=720",
        "width=1280&height=2161",
    ],
)
def test_overlay_rejects_bad_sizes(client, overlay_match, fake_renderer, query):
    resp = client.get(overlay_url(overlay_match.event, overlay_match.uuid, query))

    assert resp.status_code == 400
    assert resp.get_json()["success"] is False
    assert fake_renderer == []


@pytest.mark.integration
def test_overlay_unknown_match_is_404(client, overlay_match, fake_renderer):
    resp = client.get(overlay_url(overlay_match.event, "no-such-match"))

    assert resp.status_code == 404


@pytest.mark.integration
def test_overlay_unpublished_tournament_is_404_for_anonymous(client, test_db, fake_renderer):
    cfg = make_registrable_config()
    hidden = Tournament(
        url="hidden-cup",
        name="Hidden Cup",
        start_date=datetime.now(timezone.utc),
        end_date=datetime.now(timezone.utc) + timedelta(days=1),
        published=False,
        registrable_config_id=cfg.id,
    )
    db.session.add(hidden)
    db.session.flush()
    match = Match(name="G", event=hidden.url, schedule_type=ScheduleType.STATIC, started_at=MATCH_START)
    db.session.add(match)
    db.session.commit()

    resp = client.get(overlay_url(hidden.url, match.uuid))

    assert resp.status_code == 404
    assert fake_renderer == []


@pytest.mark.integration
def test_overlay_returns_frames_with_effective_times(client, overlay_match, fake_renderer):
    resp = client.get(overlay_url(overlay_match.event, overlay_match.uuid))

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["width"] == 1280
    assert body["height"] == 720
    assert [frame["effective_at"] for frame in body["frames"]] == [
        "2026-01-01T12:00:00Z",
        "2026-01-01T12:00:10Z",
        "2026-01-01T12:00:20Z",
    ]
    assert [base64.b64decode(frame["png"]) for frame in body["frames"]] == [b"png-0", b"png-1", b"png-2"]

    (call,) = fake_renderer
    assert (call["width"], call["height"]) == (1280, 720)
    last_state = call["states"][-1]
    assert last_state["team1_name"] == "Alpha Pseudo"
    assert last_state["team1_shortname"] == "ALP"
    assert last_state["team2_name"] == "Beta"
    assert last_state["team2_photo"] == "uploads/beta.png"
    assert last_state["sets"] == [1]
    assert last_state["scores_by_set"] == {1: {"team1_score": 1, "team2_score": 0}}


@pytest.mark.integration
def test_overlay_renderer_unavailable_is_503(client, overlay_match, monkeypatch):
    monkeypatch.setattr(
        "app.routes.tournaments.scoreboard_overlay.render_scoreboard_frames",
        lambda states, width, height: Err(ArctosError("Scoreboard renderer is unavailable", status_code=503)),
    )

    resp = client.get(overlay_url(overlay_match.event, overlay_match.uuid))

    assert resp.status_code == 503
    assert resp.get_json()["error"] == "Scoreboard renderer is unavailable"


@pytest.mark.integration
def test_overlay_without_frontend_url_is_503(client, overlay_match, monkeypatch):
    monkeypatch.delenv("ARCTOS_FRONTEND_URL", raising=False)

    resp = client.get(overlay_url(overlay_match.event, overlay_match.uuid))

    assert resp.status_code == 503
    assert "not configured" in resp.get_json()["error"]


@pytest.mark.integration
def test_live_scoreboard_state_for_active_match(client, overlay_match):
    resp = client.get(f"/_api/scoreboard-state?tournament={overlay_match.event}&field=Field 1")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["has_active_match"] is True
    assert body["match_id"] == overlay_match.uuid
    assert body["team1_name"] == "Alpha Pseudo"
    assert body["team2_photo"] == "uploads/beta.png"
    assert body["sets"] == [1]
    assert body["scores_by_set"] == {"1": {"team1_score": 1, "team2_score": 0}}
    assert body["stones_info"] is None
    assert body["points_for_stones"] is None
