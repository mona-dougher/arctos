"""Tests for a team declining a player's pending registration request."""

import pytest

from app.domain.enums import RegistrationStatus
from models import PlayerRegistration, db
from tests.utils import login_as


@pytest.mark.integration
def test_declined_player_becomes_confirmed_unattached(app, client, tournament, player, team, team_registration):
    with app.app_context():
        tournament_url = db.session.merge(tournament).url
        reg = PlayerRegistration(
            event=tournament_url,
            player=db.session.merge(player).id,
            team=db.session.merge(team).id,
            status=RegistrationStatus.PENDING_TEAM_APPROVAL,
            jersey_name="Alice",
            jersey_number="7",
        )
        db.session.add(reg)
        db.session.commit()
        reg_id = reg.id
        login_as(client, db.session.merge(team))

    resp = client.post(f"/_api/{tournament_url}/invitation/{reg_id}/decline")
    assert resp.status_code == 200

    with app.app_context():
        reg = PlayerRegistration.query.get(reg_id)
        assert reg.status == RegistrationStatus.CONFIRMED
        assert reg.team is None
        assert reg.jersey_name == "Alice"


@pytest.mark.integration
def test_league_declined_player_becomes_confirmed_unattached(app, client, player, team):
    from app.domain.enums import TeamRegistrationStatus
    from models import League, TeamRegistration
    from tests.utils import make_registrable_config

    with app.app_context():
        league = League(url="decline-lg", name="Decline League", registrable_config_id=make_registrable_config().id)
        db.session.add(league)
        db.session.flush()
        team_id = db.session.merge(team).id
        db.session.add(
            TeamRegistration(
                event=None,
                league_id=league.url,
                team=team_id,
                status=TeamRegistrationStatus.CONFIRMED,
            )
        )
        reg = PlayerRegistration(
            event=None,
            league_id=league.url,
            player=db.session.merge(player).id,
            team=team_id,
            status=RegistrationStatus.PENDING_TEAM_APPROVAL,
            jersey_name="Alice",
            jersey_number="7",
        )
        db.session.add(reg)
        db.session.commit()
        reg_id = reg.id
        login_as(client, db.session.merge(team))

    resp = client.post(f"/_api/leagues/decline-lg/invitation/{reg_id}/decline")
    assert resp.status_code == 200

    with app.app_context():
        reg = PlayerRegistration.query.get(reg_id)
        assert reg.status == RegistrationStatus.CONFIRMED
        assert reg.team is None
