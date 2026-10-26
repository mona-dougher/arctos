"""Standings selection, publication limits, and organizer access."""

import pytest

from app.domain.enums import Pompfen
from models import TO, League, Player, SideComp, SideCompRegistration, SideCompResult, db
from tests.utils import issue_access_token, login_as

pytestmark = pytest.mark.integration


def _add_entry(comp, player_id, weapon, wins, losses=0):
    player = Player(id=player_id, name=player_id, pw_hash="unused")
    db.session.add(player)
    db.session.flush()
    entry = SideCompRegistration(
        comp=comp.id,
        player=player.id,
        entry_number=SideCompRegistration.query.filter_by(comp=comp.id).count() + 1,
        weapon=weapon.value if weapon is not None else None,
    )
    db.session.add(entry)
    db.session.flush()
    for points in [1] * wins + [-1] * losses:
        db.session.add(SideCompResult(comp=comp.id, player=entry.id, points=points, ref="ref"))
    db.session.commit()
    return entry


@pytest.fixture
def chain_pit(tournament):
    comp = SideComp(
        event=tournament.url,
        name="Chain pit",
        type="CHAIN_BREAKING",
        only_show_top_n_results=3,
    )
    db.session.add(comp)
    db.session.commit()
    for index, wins in enumerate((9, 8, 7)):
        _add_entry(comp, f"staff-{index}", Pompfen.STAFF, wins)
    for index, wins in enumerate((6, 5, 4, 3)):
        _add_entry(comp, f"florentine-{index}", Pompfen.FLORENTINE, wins)
    _add_entry(comp, "chain-0", Pompfen.CHAIN, 3)
    _add_entry(comp, "chain-1", Pompfen.CHAIN, 2)
    _add_entry(comp, "incomplete", None, 10)
    return comp


def test_weapon_selection_fills_top_three_from_complete_standings(client, chain_pit):
    path = f"/_api/sidecomps/{chain_pit.id}/standings"
    initial = client.get(path).get_json()
    assert initial["showing_all_results"] is False
    chains, breaks = initial["tables"]
    assert chains["available_weapons"] == ["CHAIN"]
    assert breaks["available_weapons"] == ["STAFF", "FLORENTINE"]
    assert [row["player_id"] for row in breaks["rows"]] == ["staff-0", "staff-1", "staff-2"]

    response = client.get(path, query_string={"table": "breaks", "weapon": "FLORENTINE"})
    assert response.status_code == 200
    [filtered] = response.get_json()["tables"]
    assert filtered["id"] == "breaks"
    assert filtered["weapon"] == "FLORENTINE"
    assert filtered["sort"] == "wins"
    assert filtered["available_weapons"] == breaks["available_weapons"]
    assert [row["player_id"] for row in filtered["rows"]] == ["florentine-0", "florentine-1", "florentine-2"]
    assert [row["rank"] for row in filtered["rows"]] == [1, 2, 3]
    assert [row["wins"] for row in filtered["rows"]] == [6, 5, 4]

    [chains] = client.get(path, query_string={"table": "chains"}).get_json()["tables"]
    assert [row["player_id"] for row in chains["rows"]] == ["chain-0", "chain-1"]

    [empty] = client.get(path, query_string={"table": "breaks", "weapon": "LONG"}).get_json()["tables"]
    assert empty["rows"] == []
    assert empty["available_weapons"] == ["STAFF", "FLORENTINE"]


def test_sort_selection_precedes_limit_and_respects_each_tables_loss_setting(client, chain_pit):
    chain_pit.track_break_losses = True
    entry = SideCompRegistration.query.filter_by(comp=chain_pit.id, player="florentine-0").one()
    for _ in range(6):
        db.session.add(SideCompResult(comp=chain_pit.id, player=entry.id, points=-1, ref="ref"))
    db.session.add(SideCompResult(comp=chain_pit.id, player=entry.id, points=1, ref="ref", valid=False))
    db.session.commit()
    path = f"/_api/sidecomps/{chain_pit.id}/standings"
    selection = {"table": "breaks", "weapon": "FLORENTINE"}

    [by_percentage] = client.get(path, query_string=selection).get_json()["tables"]
    assert by_percentage["sort"] == "win_percentage"
    assert [row["player_id"] for row in by_percentage["rows"]] == [
        "florentine-1",
        "florentine-2",
        "florentine-3",
    ]

    [by_wins] = client.get(path, query_string={**selection, "sort": "wins"}).get_json()["tables"]
    assert by_wins["sort"] == "wins"
    assert [row["player_id"] for row in by_wins["rows"]] == ["florentine-0", "florentine-1", "florentine-2"]
    assert by_wins["rows"][0]["wins"] == 6
    assert by_wins["rows"][0]["losses"] == 6
    assert by_wins["rows"][0]["win_percentage"] == 50

    [chains] = client.get(path, query_string={"table": "chains", "sort": "win_percentage"}).get_json()["tables"]
    assert chains["sort"] == "wins"
    assert chains["track_losses"] is False
    assert all(row["losses"] is None for row in chains["rows"])


def test_filtered_ties_use_entry_number_and_unplayed_entries_follow_played(client, tournament):
    comp = SideComp(event=tournament.url, name="Duels", type="DUELING", track_losses=True)
    db.session.add(comp)
    db.session.commit()
    _add_entry(comp, "unplayed", Pompfen.FLORENTINE, 0)
    _add_entry(comp, "early", Pompfen.FLORENTINE, 2, 2)
    _add_entry(comp, "late", Pompfen.FLORENTINE, 2, 2)
    _add_entry(comp, "busy", Pompfen.FLORENTINE, 3, 3)
    _add_entry(comp, "other-weapon", Pompfen.STAFF, 4)

    response = client.get(f"/_api/sidecomps/{comp.id}/standings?table=all&weapon=FLORENTINE&sort=win_percentage")
    [table] = response.get_json()["tables"]
    assert [row["player_id"] for row in table["rows"]] == ["busy", "early", "late", "unplayed"]
    assert [row["rank"] for row in table["rows"]] == [1, 2, 3, 4]
    assert table["rows"][-1]["win_percentage"] is None


@pytest.mark.parametrize("scope", ["tournament", "league"])
@pytest.mark.parametrize("is_organizer", [False, True])
def test_only_scope_organizers_receive_every_matching_player(client, tournament, chain_pit, scope, is_organizer):
    viewer = Player(id="viewer", name="Viewer", pw_hash="unused")
    db.session.add(viewer)
    if scope == "league":
        league = League(url="league", name="League", registrable_config_id=tournament.registrable_config_id)
        db.session.add(league)
        db.session.flush()
        tournament.league_id = league.url
        tournament.registrable_config_id = None
    db.session.flush()
    if is_organizer:
        db.session.add(
            TO(
                user_id=viewer.id,
                user_type="player",
                event=tournament.url if scope == "tournament" else None,
                league_id=tournament.league_id if scope == "league" else None,
            )
        )
    db.session.commit()
    login_as(client, viewer)

    response = client.get(
        f"/_api/sidecomps/{chain_pit.id}/standings",
        query_string={"table": "breaks", "weapon": "FLORENTINE", "include_below_cut": "true"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["showing_all_results"] is is_organizer
    [table] = payload["tables"]
    assert len(table["rows"]) == (4 if is_organizer else 3)


@pytest.mark.parametrize("top_n, expected_count", [(None, 4), (0, 0), (2, 2)])
@pytest.mark.parametrize("finalized", [False, True])
def test_publication_limit_applies_to_filtered_results_in_every_state(
    client, chain_pit, top_n, expected_count, finalized
):
    chain_pit.only_show_top_n_results = top_n
    chain_pit.finalized = finalized
    db.session.commit()

    response = client.get(f"/_api/sidecomps/{chain_pit.id}/standings?table=breaks&weapon=FLORENTINE")
    payload = response.get_json()
    assert payload["results_page_enabled"] is (top_n != 0)
    assert payload["showing_all_results"] is (top_n is None)
    assert payload["finalized"] is finalized
    assert len(payload["tables"][0]["rows"]) == expected_count


@pytest.mark.parametrize(
    "query",
    [
        {"table": "unknown"},
        {"table": "chains"},
        {"table": ""},
        {"weapon": "unknown"},
        {"weapon": "5"},
        {"weapon": ""},
        {"sort": "unknown"},
        {"sort": ""},
    ],
)
def test_invalid_standings_selection_returns_validation_error(client, tournament, query):
    comp = SideComp(event=tournament.url, name="Duels", type="DUELING")
    db.session.add(comp)
    db.session.commit()

    response = client.get(f"/_api/sidecomps/{comp.id}/standings", query_string=query)
    assert response.status_code == 400
    assert "Invalid standings" in response.get_json()["error"]


def test_public_api_keeps_default_cap_even_for_an_organizer_token(client, tournament, chain_pit):
    organizer = Player(id="organizer", name="Organizer", pw_hash="unused")
    db.session.add(organizer)
    db.session.flush()
    db.session.add(TO(user_id=organizer.id, user_type="player", event=tournament.url))
    db.session.commit()
    token = issue_access_token(organizer)
    path = f"/api/v1/tournaments/{tournament.url}/side-competitions/{chain_pit.id}/results"
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get(path, headers=headers)
    assert response.status_code == 200
    chains, breaks = response.get_json()["tables"]
    assert set(breaks) == {"id", "title", "track_losses", "rows"}
    assert [row["player"]["id"] for row in breaks["rows"]] == ["staff-0", "staff-1", "staff-2"]
    assert len(chains["rows"]) == 2

    chain_pit.only_show_top_n_results = 0
    db.session.commit()
    assert client.get(path, headers=headers).status_code == 404
