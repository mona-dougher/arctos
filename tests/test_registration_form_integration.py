"""Registration prerequisites are checked before state changes and stay private."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from flask import g

from app.domain.enums import RegistrationStatus
from app.error_values import Err, Ok
from app.exceptions import ArctosError, ValidationError
from app.services._common import Scope
from app.services.registration_form_service import RegistrationFormService
from app.services.registration_service import RegistrationService
from models import League, Player, PlayerRegistration, Team, TO, Tournament, db
from tests.utils import login_as as _login_as, make_registrable_config

pytestmark = pytest.mark.integration

FORM_FIELDS = {
    "registration_form_url": "https://docs.google.com/forms/d/e/test-form/viewform",
    "registration_form_sheet_id": "private-response-sheet",
    "registration_form_sheet_gid": 0,
    "registration_form_username_column": "Arctos username",
}
PRIVATE_KEYS = {
    "registration_form_sheet_url",
    "registration_form_username_column",
    "registration_form_service_account_email",
    "registration_form_available",
    "registration_form_sheet_id",
    "registration_form_sheet_gid",
}


@pytest.fixture(params=["tournament", "league"])
def scope(request, tournament, player, team):
    kind = request.param
    if kind == "tournament":
        entity = tournament
        root = f"/_api/{entity.url}"
        detail = f"/_api/tournaments/{entity.url}"
        service_scope = Scope.event(entity.url)
        registration_fields = {"event": entity.url}
        owner_fields = {"event": entity.url}
        settings_url = root + "/update-settings"
    else:
        entity = League(
            url="forms-league",
            name="Forms League",
            published=True,
            registrable_config_id=make_registrable_config(player_registration_open=True).id,
        )
        db.session.add(entity)
        db.session.flush()
        root = f"/_api/leagues/{entity.url}"
        detail = root
        service_scope = Scope.league(entity.url)
        registration_fields = {"league_id": entity.url}
        owner_fields = {"league_id": entity.url}
        settings_url = root + "/settings"
    config = entity.registrable_config
    for key, value in FORM_FIELDS.items():
        setattr(config, key, value)
    organizer = Player(id="forms-organizer", name="Form Organizer", pw_hash="test")
    db.session.add(organizer)
    db.session.add(TO(user_id=organizer.id, user_type="player", **owner_fields))
    db.session.commit()
    return SimpleNamespace(
        kind=kind,
        entity=entity,
        config=config,
        root=root,
        detail=detail,
        settings_url=settings_url,
        service_scope=service_scope,
        registration_fields=registration_fields,
        organizer=organizer,
        player=player,
        team=team,
        edit_url=detail + "/registrations/player/me",
    )


def login_as(client, user):
    g.pop("_login_user", None)
    _login_as(client, user)


def requirement_stub(monkeypatch, scope, outcome):
    calls = []

    def require(config, username):
        assert config is scope.config
        calls.append(username)
        return outcome

    monkeypatch.setattr(RegistrationFormService, "require_response", staticmethod(require))
    return calls


def unavailable():
    return Err(ArctosError("Form verification is unavailable. Try again shortly.", status_code=503))


def registration(scope, *, status=RegistrationStatus.PENDING_TEAM_APPROVAL):
    row = PlayerRegistration(
        **scope.registration_fields,
        player=scope.player.id,
        team=scope.team.id,
        jersey_name="Original",
        jersey_number="7",
        status=status,
        paid=False,
        amount_paid=12,
        waiver_legal_name_signature="Original signature",
        waiver_legal_name_signature_sha256="original-checksum",
    )
    db.session.add(row)
    db.session.commit()
    return row


def row_values(row):
    return (
        row.team,
        row.jersey_name,
        row.jersey_number,
        row.status,
        row.paid,
        row.amount_paid,
        row.paid_at,
        row.waiver_legal_name_signature,
        row.waiver_legal_name_signature_sha256,
    )


@pytest.mark.parametrize("team_request", [False, True])
@pytest.mark.parametrize("failure", ["missing", "unavailable"])
def test_registration_requires_response_and_preserves_http_status(client, scope, monkeypatch, team_request, failure):
    failure_result = Err(ValidationError("Complete the registration form.")) if failure == "missing" else unavailable()
    calls = requirement_stub(monkeypatch, scope, failure_result)
    login_as(client, scope.player)
    data = {"jersey_name": "New", "jersey_number": "12"}
    if team_request:
        data["team"] = scope.team.id
    response = client.post(scope.root + "/register-player", data=data)
    assert response.status_code == (400 if failure == "missing" else 503)
    assert calls == [scope.player.id]
    assert PlayerRegistration.query.filter_by(**scope.registration_fields).count() == 0

    requirement_stub(monkeypatch, scope, Ok(None))
    response = client.post(scope.root + "/register-player", data=data)
    assert response.status_code == 200, response.get_json()
    row = PlayerRegistration.query.filter_by(**scope.registration_fields).one()
    expected = RegistrationStatus.PENDING_TEAM_APPROVAL if team_request else RegistrationStatus.CONFIRMED
    assert row.status == expected
    assert row.jersey_name == "New"


@pytest.mark.parametrize("status", [RegistrationStatus.CANCELLED, RegistrationStatus.REJECTED])
def test_failed_reregistration_leaves_existing_row_clean(scope, monkeypatch, status):
    row = registration(scope, status=status)
    before = row_values(row)
    scope.config.waiver_filepath = "waiver.pdf"
    scope.config.waiver_sha256 = "current-checksum"
    db.session.commit()
    requirement_stub(monkeypatch, scope, unavailable())
    result = RegistrationService.register_player(
        scope.service_scope,
        scope.player.id,
        None,
        jersey_name="Changed",
        jersey_number="99",
        waiver_legal_name_signature="New signature",
    )
    assert isinstance(result, Err)
    assert not db.session.is_modified(row)
    db.session.commit()
    db.session.refresh(row)
    assert row_values(row) == before


def test_local_validation_precedes_form_lookup(scope, monkeypatch):
    calls = requirement_stub(monkeypatch, scope, unavailable())
    scope.config.waiver_filepath = "waiver.pdf"
    scope.config.waiver_sha256 = "checksum"
    db.session.commit()
    result = RegistrationService.register_player(scope.service_scope, scope.player.id, None)
    assert isinstance(result, Err)
    assert "Waiver signature" in result.unwrap_err().message
    assert calls == []


@pytest.mark.parametrize("action", ["accept", "decline"])
def test_pending_team_decisions_verify_before_mutation(client, scope, monkeypatch, action):
    row = registration(scope)
    before = row_values(row)
    login_as(client, scope.team)
    calls = requirement_stub(monkeypatch, scope, unavailable())
    endpoint = f"{scope.root}/invitation/{row.id}/{action}"
    response = client.post(endpoint)
    assert response.status_code == 503
    assert calls == [scope.player.id]
    db.session.refresh(row)
    assert row_values(row) == before

    requirement_stub(monkeypatch, scope, Ok(None))
    assert client.post(endpoint).status_code == 200
    db.session.refresh(row)
    assert row.status == RegistrationStatus.CONFIRMED
    assert row.team == (scope.team.id if action == "accept" else None)


def test_team_decision_checks_ownership_before_lookup(client, scope, monkeypatch):
    row = registration(scope)
    other_team = Team(id="other-team", name="Other", pw_hash="test")
    db.session.add(other_team)
    db.session.commit()
    login_as(client, other_team)
    calls = requirement_stub(monkeypatch, scope, unavailable())
    assert client.post(f"{scope.root}/invitation/{row.id}/accept").status_code == 404
    assert calls == []


def test_pending_self_removal_preserves_all_fields_on_verification_failure(client, scope, monkeypatch):
    row = registration(scope)
    before = row_values(row)
    login_as(client, scope.player)
    requirement_stub(monkeypatch, scope, unavailable())
    data = {"team": None, "jersey_name": "Changed", "jersey_number": "99"}
    response = client.put(scope.edit_url, json=data)
    assert response.status_code == 503
    db.session.refresh(row)
    assert row_values(row) == before

    requirement_stub(monkeypatch, scope, Ok(None))
    assert client.put(scope.edit_url, json=data).status_code == 200
    db.session.refresh(row)
    assert row.status == RegistrationStatus.CONFIRMED and row.team is None
    assert row.jersey_name == "Changed"


def test_confirmed_players_keep_registration_when_requirement_changes(client, scope, monkeypatch):
    row = registration(scope, status=RegistrationStatus.CONFIRMED)
    login_as(client, scope.player)
    calls = requirement_stub(monkeypatch, scope, unavailable())
    assert client.put(scope.edit_url, json={"team": None, "jersey_name": "Updated"}).status_code == 200
    db.session.refresh(row)
    assert row.status == RegistrationStatus.CONFIRMED
    assert row.jersey_name == "Updated"
    assert calls == []


@pytest.mark.parametrize("scope", ["tournament"], indirect=True)
def test_organizer_registration_verifies_target_before_changes(client, scope, monkeypatch):
    row = registration(scope, status=RegistrationStatus.CANCELLED)
    before = row_values(row)
    calls = requirement_stub(monkeypatch, scope, unavailable())
    login_as(client, scope.organizer)
    response = client.post(scope.root + "/register-player-as-to", json={"player_id": scope.player.id})
    assert response.status_code == 503
    assert calls == [scope.player.id]
    db.session.refresh(row)
    assert row_values(row) == before
    requirement_stub(monkeypatch, scope, Ok(None))
    assert client.post(scope.root + "/register-player-as-to", json={"player_id": scope.player.id}).status_code == 200
    db.session.refresh(row)
    assert row.status == RegistrationStatus.CONFIRMED


def settings_payload(scope, **changes):
    data = {
        "registration_form_required": "true" if scope.kind == "tournament" else True,
        "registration_form_url": FORM_FIELDS["registration_form_url"],
        "registration_form_sheet_url": "https://docs.google.com/spreadsheets/d/private-response-sheet/edit#gid=0",
        "registration_form_username_column": "Arctos username",
        "about": "Updated information",
    }
    if scope.kind == "tournament":
        data.update(name=scope.entity.name, end_date="2030-12-31", player_registration_open="on")
    data.update(changes)
    return data


def post_settings(client, scope, data):
    return client.post(scope.settings_url, **({"data": data} if scope.kind == "tournament" else {"json": data}))


def test_settings_verify_before_committing_other_fields(client, scope, monkeypatch):
    before_about = scope.entity.about
    before_config = {key: getattr(scope.config, key) for key in FORM_FIELDS}
    calls = []

    def validate(**values):
        calls.append(values)
        return unavailable()

    monkeypatch.setattr(RegistrationFormService, "validate_settings", staticmethod(validate))
    login_as(client, scope.organizer)
    response = post_settings(client, scope, settings_payload(scope))
    assert response.status_code == 503
    assert calls[0]["enabled"] is True
    db.session.refresh(scope.entity)
    db.session.refresh(scope.config)
    assert scope.entity.about == before_about
    assert {key: getattr(scope.config, key) for key in FORM_FIELDS} == before_config

    monkeypatch.setattr(RegistrationFormService, "validate_settings", staticmethod(lambda **_: Ok(FORM_FIELDS)))
    response = post_settings(client, scope, settings_payload(scope))
    assert response.status_code == 200, response.get_json()
    db.session.refresh(scope.entity)
    assert scope.entity.about == "Updated information"


def test_settings_omission_preserves_requirement_and_explicit_disable_clears_it(client, scope):
    login_as(client, scope.organizer)
    data = {key: value for key, value in settings_payload(scope).items() if not key.startswith("registration_form_")}
    assert post_settings(client, scope, data).status_code == 200
    db.session.refresh(scope.config)
    assert scope.config.registration_form_url == FORM_FIELDS["registration_form_url"]
    data["registration_form_required"] = "false" if scope.kind == "tournament" else False
    assert post_settings(client, scope, data).status_code == 200
    db.session.refresh(scope.config)
    assert all(getattr(scope.config, key) is None for key in FORM_FIELDS)


def test_settings_require_boolean_choice_and_permission_before_provider(client, scope, monkeypatch):
    def unexpected(**_):
        pytest.fail("Invalid or unauthorized settings must not contact Google")

    monkeypatch.setattr(RegistrationFormService, "validate_settings", staticmethod(unexpected))
    login_as(client, scope.player)
    assert post_settings(client, scope, settings_payload(scope)).status_code == 403
    login_as(client, scope.organizer)
    assert (
        post_settings(client, scope, settings_payload(scope, registration_form_required="invalid")).status_code == 400
    )
    data = settings_payload(scope)
    del data["registration_form_required"]
    assert post_settings(client, scope, data).status_code == 400


def test_response_sheet_settings_are_organizer_only(client, scope):
    for user in (None, scope.player, scope.team):
        g.pop("_login_user", None)
        with client.session_transaction() as session:
            session.clear()
        if user is not None:
            login_as(client, user)
        payload = client.get(scope.detail).get_json()[scope.kind]
        assert payload["registration_form_required"] is True
        assert payload["registration_form_url"] == FORM_FIELDS["registration_form_url"]
        assert PRIVATE_KEYS.isdisjoint(payload)
        assert "private-response-sheet" not in str(payload)

    login_as(client, scope.organizer)
    payload = client.get(scope.detail).get_json()[scope.kind]
    assert "private-response-sheet" in payload["registration_form_sheet_url"]
    assert payload["registration_form_username_column"] == "Arctos username"
    listing = client.get("/_api/tournaments" if scope.kind == "tournament" else "/_api/leagues").get_json()
    assert "private-response-sheet" not in str(listing)

    # User type is part of organizer identity even when the textual ID matches.
    matching_team = Team(id=scope.organizer.id, name="Unrelated team", pw_hash="test")
    db.session.add(matching_team)
    db.session.commit()
    # Supply the resolved principal directly: legacy session IDs contain no
    # account type, so their loader selects the player when IDs collide.
    g._login_user = matching_team
    assert PRIVATE_KEYS.isdisjoint(client.get(scope.detail).get_json()[scope.kind])


@pytest.mark.parametrize("scope", ["league"], indirect=True)
def test_league_event_inherits_public_requirement_and_rejects_event_settings(client, scope):
    event = Tournament(
        url="forms-league-round",
        name="League Round",
        league_id=scope.entity.url,
        published=True,
        start_date=datetime(2030, 1, 1),
        end_date=datetime(2030, 1, 1) + timedelta(days=1),
    )
    db.session.add(event)
    db.session.commit()
    payload = client.get(f"/_api/tournaments/{event.url}").get_json()["tournament"]
    assert payload["registration_form_required"] is True
    assert payload["registration_form_url"] == FORM_FIELDS["registration_form_url"]
    assert PRIVATE_KEYS.isdisjoint(payload)
    login_as(client, scope.organizer)
    response = client.post(
        f"/_api/{event.url}/update-settings",
        data={"name": event.name, "end_date": "2030-01-02", "registration_form_required": "false"},
    )
    assert response.status_code == 400
    assert "league settings" in response.get_json()["error"]
    db.session.refresh(scope.config)
    assert scope.config.registration_form_url == FORM_FIELDS["registration_form_url"]
