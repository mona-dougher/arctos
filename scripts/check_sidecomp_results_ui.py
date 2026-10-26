"""Check side competition filters, live refresh, and publication guidance.

Run against an isolated local demo. Standings responses are browser fixtures;
the shared request guard blocks data changes. Backend tests separately verify
ranking, filtering, and organizer permissions.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
import sys
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import Page, Route, async_playwright, expect

from check_mobile_ui import DEMO_USER, TIMEOUT_MS, SmokeCheck, api_json, arguments


def standing(entry_number: int, name: str, weapon: str, wins: int, losses: int | None) -> dict:
    return {
        "registration_id": entry_number,
        "entry_number": entry_number,
        "weapon": weapon,
        "player_id": name.lower().replace(" ", "-"),
        "display_name": name,
        "profile_photo": None,
        "jersey_name": name,
        "jersey_number": str(entry_number),
        "team_shortname": "DEMO",
        "team_profile_photo": None,
        "wins": wins,
        "losses": losses,
        "win_percentage": 100 * wins / (wins + losses) if losses is not None else None,
        "rank": 0,
    }


class StandingsFixture:
    def __init__(self, comp_id: int):
        self.comp_id = comp_id
        self.show_all = False
        self.public_limit = 3
        self.hidden = False
        self.empty = False
        self.fail_metadata = False
        self.fail_weapon: str | None = None
        self.delay_weapon: str | None = None
        self.delay_started = asyncio.Event()
        self.release_delay = asyncio.Event()
        self.held_policies: dict[tuple[bool, int], tuple[asyncio.Event, asyncio.Event, asyncio.Event]] = {}
        self.chains = [standing(1, "Chain A", "CHAIN", 3, None), standing(2, "Chain B", "CHAIN", 2, None)]
        self.staff = [standing(3 + index, f"Staff {index + 1}", "STAFF", 9 - index, 0) for index in range(3)]
        self.florentine = [
            standing(6, "Florentine A", "FLORENTINE", 6, 6),
            standing(7, "Florentine B", "FLORENTINE", 5, 0),
            standing(8, "Florentine C", "FLORENTINE", 4, 0),
            standing(9, "Florentine D", "FLORENTINE", 3, 0),
        ]

    def table(self, table_id: str, weapon: str | None, sort: str | None) -> dict:
        track_losses = table_id == "breaks"
        effective_sort = (sort or "win_percentage") if track_losses else "wins"
        if table_id == "chains":
            rows = self.chains
        elif weapon == "FLORENTINE":
            rows = self.florentine if effective_sort == "wins" else self.florentine[1:] + self.florentine[:1]
        elif weapon == "STAFF":
            rows = self.staff
        else:
            rows = self.staff + self.florentine
        if self.empty or self.hidden:
            rows = []
        elif not self.show_all:
            rows = rows[: self.public_limit]
        rows = deepcopy(rows)
        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank
        return {
            "id": table_id,
            "title": "Chains" if table_id == "chains" else "Breaks",
            "track_losses": track_losses,
            "available_weapons": ["CHAIN"] if table_id == "chains" else ["STAFF", "FLORENTINE"],
            "weapon": weapon,
            "sort": effective_sort,
            "rows": rows,
        }

    async def handle(self, route: Route) -> None:
        query = parse_qs(urlsplit(route.request.url).query)
        weapon = query.get("weapon", [None])[0]
        sort = query.get("sort", [None])[0]
        table_ids = query.get("table", ["chains", "breaks"])
        payload = {
            "id": self.comp_id,
            "name": "Chain pit",
            "type": "CHAIN_BREAKING",
            "finalized": False,
            "only_show_top_n_results": 0 if self.hidden else self.public_limit,
            "showing_all_results": self.show_all,
            "results_page_enabled": not self.hidden,
            "tables": [self.table(table_id, weapon, sort) for table_id in table_ids],
        }
        held_policy = self.held_policies.get((self.show_all, self.public_limit)) if weapon is not None else None
        if held_policy is not None:
            started, release, delivered = held_policy
            started.set()
            await release.wait()
        if weapon is not None and weapon == self.delay_weapon:
            self.delay_weapon = None
            self.delay_started.set()
            await self.release_delay.wait()
        if (weapon is not None and weapon == self.fail_weapon) or (not query and self.fail_metadata):
            await route.fulfill(status=503, json={"error": "Standings temporarily unavailable"})
        else:
            await route.fulfill(json=payload)
        if held_policy is not None:
            delivered.set()

    def hold_policy(self, show_all: bool, public_limit: int) -> tuple[asyncio.Event, asyncio.Event, asyncio.Event]:
        events = (asyncio.Event(), asyncio.Event(), asyncio.Event())
        self.held_policies[show_all, public_limit] = events
        return events

    def delay_next(self, weapon: str) -> None:
        self.delay_weapon = weapon
        self.delay_started.clear()
        self.release_delay.clear()


async def assert_players(section, names: list[str]) -> None:
    await expect(section.locator("tbody tr td:nth-child(3) .fw-semibold")).to_have_text(names)
    await expect(section.locator("tbody tr td:first-child")).to_have_text([str(i + 1) for i in range(len(names))])


async def verify(check: SmokeCheck, page: Page, fixture: StandingsFixture) -> None:
    await page.goto(f"{check.base_url}/demo-open/sidecomps/{fixture.comp_id}/results")
    chains = page.get_by_role("region", name="Chains", exact=True)
    breaks = page.get_by_role("region", name="Breaks", exact=True)
    await expect(page.get_by_text("The organizer publishes the top 3", exact=False)).to_be_visible()
    await assert_players(breaks, ["Staff 1", "Staff 2", "Staff 3"])
    await expect(breaks.get_by_role("button", name="Florentine", exact=True)).to_be_visible()
    await breaks.get_by_role("button", name="Florentine", exact=True).focus()
    await page.keyboard.press("Enter")
    await assert_players(breaks, ["Florentine B", "Florentine C", "Florentine D"])
    await expect(breaks.get_by_role("button", name="Florentine", exact=True)).to_have_attribute("aria-pressed", "true")
    await breaks.get_by_role("button", name="Wins", exact=True).click()
    await assert_players(breaks, ["Florentine A", "Florentine B", "Florentine C"])
    await assert_players(chains, ["Chain A", "Chain B"])
    await expect(chains.get_by_role("button", name="All", exact=True)).to_have_attribute("aria-pressed", "true")

    for width in (320, 390, 1280):
        await page.set_viewport_size({"width": width, "height": 900})
        await page.evaluate("window.scrollTo(0, 0); document.activeElement?.blur()")
        await check.check_layout(page, "sidecomp-filtered", width)
        await check.screenshot(page, "sidecomp-filtered", width)
        check.visited += 1

    # A delayed old selection must not replace the user's newer choice.
    fixture.delay_next("STAFF")
    await breaks.get_by_role("button", name="Staff", exact=True).click()
    await asyncio.wait_for(fixture.delay_started.wait(), TIMEOUT_MS / 1000)
    await expect(breaks.get_by_text("Loading standings…")).to_be_visible()
    await expect(breaks.locator("tbody tr")).to_have_count(0)
    await breaks.get_by_role("button", name="Florentine", exact=True).click()
    await assert_players(breaks, ["Florentine A", "Florentine B", "Florentine C"])
    fixture.release_delay.set()

    # A request slower than the polling interval must still finish.
    fixture.delay_next("STAFF")
    await breaks.get_by_role("button", name="Staff", exact=True).click()
    await asyncio.wait_for(fixture.delay_started.wait(), TIMEOUT_MS / 1000)
    await asyncio.sleep(1.2)
    await expect(breaks.get_by_text("Loading standings…")).to_be_visible()
    fixture.release_delay.set()
    await assert_players(breaks, ["Staff 1", "Staff 2", "Staff 3"])

    fixture.fail_weapon = "FLORENTINE"
    await breaks.get_by_role("button", name="Florentine", exact=True).click()
    await expect(breaks.get_by_role("alert")).to_contain_text("Could not load standings")
    await expect(breaks.get_by_role("button", name="Florentine", exact=True)).to_have_attribute("aria-pressed", "true")
    fixture.fail_weapon = None
    await breaks.get_by_role("button", name="Retry standings", exact=True).click()
    await assert_players(breaks, ["Florentine A", "Florentine B", "Florentine C"])
    fixture.fail_metadata = True
    await expect(page.get_by_role("alert")).to_contain_text("Could not refresh results")
    await assert_players(breaks, ["Florentine A", "Florentine B", "Florentine C"])
    await expect(breaks.get_by_role("button", name="Florentine", exact=True)).to_have_attribute("aria-pressed", "true")
    fixture.fail_metadata = False
    await page.get_by_role("button", name="Retry results", exact=True).click()
    await expect(page.get_by_role("alert")).to_have_count(0)
    check.network_errors = [
        error for error in check.network_errors if "HTTP 503" not in error or "/standings" not in error
    ]

    fixture.empty = True
    await expect(breaks.get_by_text("No players match this weapon.")).to_be_visible()
    fixture.empty = False
    fixture.show_all = True
    await expect(page.get_by_text("You can view all results as an organizer.", exact=False)).to_be_visible()
    await assert_players(breaks, ["Florentine A", "Florentine B", "Florentine C", "Florentine D"])

    # Keep the filter selected while access loss or a smaller cap invalidates rows.
    for public_limit in (3, 2):
        old_started, old_release, old_delivered = fixture.hold_policy(fixture.show_all, fixture.public_limit)
        await asyncio.wait_for(old_started.wait(), TIMEOUT_MS / 1000)
        new_started, new_release, _ = fixture.hold_policy(False, public_limit)
        fixture.show_all = False
        fixture.public_limit = public_limit
        await expect(page.get_by_text(f"The organizer publishes the top {public_limit}", exact=False)).to_be_visible()
        await asyncio.wait_for(new_started.wait(), TIMEOUT_MS / 1000)
        await expect(breaks.get_by_text("Loading standings…")).to_be_visible()
        await expect(breaks.locator("tbody tr")).to_have_count(0)
        await expect(breaks.get_by_role("button", name="Florentine", exact=True)).to_have_attribute(
            "aria-pressed", "true"
        )
        old_release.set()
        await asyncio.wait_for(old_delivered.wait(), TIMEOUT_MS / 1000)
        await page.evaluate("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
        await expect(breaks.locator("tbody tr")).to_have_count(0)
        new_release.set()
        await assert_players(breaks, ["Florentine A", "Florentine B", "Florentine C"][:public_limit])

    fixture.hidden = True
    await expect(page.get_by_text("Results are not being shown for this side competition.", exact=True)).to_be_visible()
    await expect(page.locator(".sidecomp-standings-table")).to_have_count(0)


async def run(args) -> int:
    check = SmokeCheck(args.base_url, args.screenshots)
    async with async_playwright() as playwright:
        launch = {"headless": True, "args": ["--mute-audio"]}
        if args.browser_executable:
            launch["executable_path"] = str(args.browser_executable)
        browser = await playwright.chromium.launch(**launch)
        context = await browser.new_context(viewport={"width": 390, "height": 900}, reduced_motion="reduce")
        context.set_default_timeout(TIMEOUT_MS)
        fixture = None
        try:
            marker = await api_json(context, check.base_url, "/_api/demo-info")
            assert marker.get("demo") is True and marker.get("organizer") == DEMO_USER
            competitions = await api_json(context, check.base_url, "/_api/demo-open/sidecomps")
            fixture = StandingsFixture(competitions[0]["id"])
            await context.route("**/*", check.guard_requests)
            await context.route(f"**/_api/sidecomps/{fixture.comp_id}/standings*", fixture.handle)
            page = await context.new_page()
            check.observe(page)
            await check.workflow(page, "sidecomp-standings", 390, lambda: verify(check, page, fixture))
        finally:
            if fixture is not None:
                fixture.release_delay.set()
                for _, release, _ in fixture.held_policies.values():
                    release.set()
            await context.close()
            await browser.close()
    print(f"{check.visited} standings screens; {check.workflows} workflows; {len(check.failures)} failures.")
    if check.failures:
        print("\n".join(check.failures), file=sys.stderr)
    return int(bool(check.failures))


if __name__ == "__main__":
    sys.exit(asyncio.run(run(arguments(__doc__))))
