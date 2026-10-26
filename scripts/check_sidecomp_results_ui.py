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

from check_appearance_ui import PALETTES, check_contrast, choose, close_menu, preference
from check_mobile_ui import DEMO_USER, TIMEOUT_MS, SmokeCheck, api_json, arguments


WEAPONS = {
    "CHAIN": "Chain",
    "LONG": "Long",
    "QTIP": "Q-Tip",
    "STAFF": "Staff",
    "BOARD": "Board",
    "FLORENTINE": "Florentine",
    "SKULL": "Skull",
    "UNARMED": "Unarmed",
}
LONG_NAME = "Alexandria Montgomery-Worthington"
UNBROKEN_NAME = "LongPlayerWithAnUnbrokenName"


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
        "win_percentage": 100 * wins / (wins + losses) if losses is not None and wins + losses else None,
        "rank": 0,
    }


class StandingsFixture:
    def __init__(self, comp_id: int):
        self.comp_id = comp_id
        self.show_all = False
        self.public_limit = 3
        self.hidden = False
        self.empty = False
        self.generic = False
        self.large_numbers = False
        self.removed_weapon: str | None = None
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

        self.all_weapons = [
            standing(10 + index, LONG_NAME if index == 0 else f"{label} Player", weapon, 12 - index, 0)
            for index, (weapon, label) in enumerate(WEAPONS.items())
        ]
        self.all_weapons[-1].update(wins=0, losses=0, win_percentage=None)
        self.all_weapons[0].update(
            entry_number=12345, wins=123, jersey_name="MontgomeryWorthington", team_shortname="NORTHWESTJUGGER"
        )
        self.all_weapons[1]["display_name"] = UNBROKEN_NAME

    def table(self, table_id: str, weapon: str | None, sort: str | None) -> dict:
        track_losses = table_id != "chains"
        effective_sort = (sort or "win_percentage") if track_losses else "wins"
        if self.generic:
            rows = self.all_weapons
        elif table_id == "chains":
            rows = self.chains
        else:
            rows = self.staff + self.florentine
        if self.removed_weapon is not None:
            rows = [row for row in rows if row["weapon"] != self.removed_weapon]
        available_weapons = [value for value in WEAPONS if any(row["weapon"] == value for row in rows)]
        if weapon is not None:
            rows = [row for row in rows if row["weapon"] == weapon]
        rows = sorted(
            rows,
            key=lambda row: (row[effective_sort] if row[effective_sort] is not None else -1, row["wins"]),
            reverse=True,
        )
        if self.empty or self.hidden:
            rows = []
        elif not self.show_all:
            rows = rows[: self.public_limit]
        rows = deepcopy(rows)
        for rank, row in enumerate(rows, start=1):
            row["rank"] = 2_147_483_600 + rank if self.large_numbers else rank
            if self.large_numbers:
                row.update(wins=2_147_483_647, losses=2_147_483_647, win_percentage=50)
        return {
            "id": table_id,
            "title": {"all": "Standings", "chains": "Chains", "breaks": "Breaks"}[table_id],
            "track_losses": track_losses,
            "available_weapons": available_weapons,
            "weapon": weapon,
            "sort": effective_sort,
            "rows": rows,
        }

    async def handle(self, route: Route) -> None:
        query = parse_qs(urlsplit(route.request.url).query)
        weapon = query.get("weapon", [None])[0]
        sort = query.get("sort", [None])[0]
        table_ids = query.get("table", ["all"] if self.generic else ["chains", "breaks"])
        payload = {
            "id": self.comp_id,
            "name": "Weapon standings" if self.generic else "Chain pit",
            "type": "OTHER" if self.generic else "CHAIN_BREAKING",
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
    await expect(section.locator("tbody tr td:nth-child(2) .fw-semibold")).to_have_text(names)
    await expect(section.locator("tbody tr td:first-child")).to_have_text([str(i + 1) for i in range(len(names))])


async def check_table_layout(page: Page, allow_horizontal_scroll: bool = False) -> None:
    """Check column alignment, complete cell text, and usable controls."""
    diagnostics = await page.locator(".sidecomp-standings-table").evaluate_all(
        """(tables, allowScroll) => tables.map(table => {
        const wrapper = table.parentElement;
        const cells = [...table.querySelectorAll('th, td')];
        return {
            title: table.caption?.textContent,
            width: wrapper.clientWidth,
            contentWidth: wrapper.scrollWidth,
            overflowingCells: cells.filter(cell => cell.scrollWidth > cell.clientWidth + 1)
                .map(cell => cell.textContent.trim()),
            missingScopes: [...table.querySelectorAll('th')].filter(cell => cell.scope !== 'col').length,
            unalignedNumbers: [...table.querySelectorAll('.table-number')]
                .filter(cell => getComputedStyle(cell).textAlign !== 'right').length,
            smallControls: [...table.closest('section').querySelectorAll('select, .results-sort-button')]
                .flatMap(control => {
                    const rect = control.getBoundingClientRect();
                    const outside = !allowScroll && (rect.left < -1 || rect.right > innerWidth + 1);
                    return rect.width < 43.9 || rect.height < 43.9 || outside
                        ? [{text: control.textContent.trim(), width: rect.width, height: rect.height}] : [];
                }),
            columnCounts: [...table.rows].map(row => row.cells.length)
        };
    })""",
        allow_horizontal_scroll,
    )
    assert diagnostics, "No standings table rendered"
    for table in diagnostics:
        assert table["title"] and "Rankings are highest first" in table["title"], table
        if not allow_horizontal_scroll:
            assert table["contentWidth"] <= table["width"] + 1, f"Scores require horizontal scrolling: {table}"
        assert not table["overflowingCells"], f"Standings text overflows a cell: {table}"
        assert not table["missingScopes"] and not table["unalignedNumbers"], table
        assert not table["smallControls"], f"Standings controls are clipped or smaller than 44px: {table}"
        assert len(set(table["columnCounts"])) == 1, f"Headers and rows have different columns: {table}"


async def check_keyboard_focus(control) -> None:
    await control.focus()
    await expect(control).to_be_focused()
    focus = await control.evaluate("""control => {
        const style = getComputedStyle(control);
        return {visible: control.matches(':focus-visible'), outline: style.outlineStyle,
            width: parseFloat(style.outlineWidth), shadow: style.boxShadow};
    }""")
    assert focus["visible"] and ((focus["outline"] != "none" and focus["width"] >= 2) or focus["shadow"] != "none"), (
        f"Keyboard focus is not visible: {focus}"
    )


async def verify(check: SmokeCheck, page: Page, fixture: StandingsFixture) -> None:
    await page.goto(f"{check.base_url}/demo-open/sidecomps/{fixture.comp_id}/results")
    chains = page.get_by_role("region", name="Chains", exact=True)
    breaks = page.get_by_role("region", name="Breaks", exact=True)
    await expect(page.get_by_text("The organizer publishes the top 3", exact=False)).to_be_visible()
    await assert_players(breaks, ["Staff 1", "Staff 2", "Staff 3"])
    weapon = breaks.get_by_role("combobox", name="Weapon", exact=True)
    await weapon.select_option("FLORENTINE")
    await assert_players(breaks, ["Florentine B", "Florentine C", "Florentine D"])
    await expect(weapon).to_have_value("FLORENTINE")
    await breaks.get_by_role("button", name="Wins", exact=True).click()
    await assert_players(breaks, ["Florentine A", "Florentine B", "Florentine C"])
    await assert_players(chains, ["Chain A", "Chain B"])
    await expect(chains.get_by_role("combobox")).to_have_count(0)
    await expect(chains.locator("thead th")).to_have_text(["Rank", "Player", "Wins↓"])

    for width in (320, 390, 1280):
        await page.set_viewport_size({"width": width, "height": 900})
        await page.evaluate("window.scrollTo(0, 0); document.activeElement?.blur()")
        await check_table_layout(page)
        await check.check_layout(page, "sidecomp-filtered", width)
        if check.screenshots:
            await breaks.screenshot(path=str(check.screenshots / f"{width:04d}-sidecomp-breaks.png"))
        check.visited += 1

    # A delayed old selection must not replace the user's newer choice.
    fixture.delay_next("STAFF")
    await weapon.select_option("STAFF")
    await asyncio.wait_for(fixture.delay_started.wait(), TIMEOUT_MS / 1000)
    await expect(breaks.get_by_text("Loading standings…")).to_be_visible()
    await expect(breaks.locator("tbody tr")).to_have_count(0)
    await weapon.select_option("FLORENTINE")
    await assert_players(breaks, ["Florentine A", "Florentine B", "Florentine C"])
    fixture.release_delay.set()

    # A request slower than the polling interval must still finish.
    fixture.delay_next("STAFF")
    await weapon.select_option("STAFF")
    await asyncio.wait_for(fixture.delay_started.wait(), TIMEOUT_MS / 1000)
    await asyncio.sleep(1.2)
    await expect(breaks.get_by_text("Loading standings…")).to_be_visible()
    fixture.release_delay.set()
    await assert_players(breaks, ["Staff 1", "Staff 2", "Staff 3"])

    fixture.fail_weapon = "FLORENTINE"
    await weapon.select_option("FLORENTINE")
    await expect(breaks.get_by_role("alert")).to_contain_text("Could not load standings")
    await expect(weapon).to_have_value("FLORENTINE")
    await breaks.get_by_role("button", name="Retry standings", exact=True).focus()
    fixture.fail_weapon = None
    await page.keyboard.press("Enter")
    await assert_players(breaks, ["Florentine A", "Florentine B", "Florentine C"])
    fixture.fail_metadata = True
    await expect(page.get_by_role("alert")).to_contain_text("Could not refresh results")
    await assert_players(breaks, ["Florentine A", "Florentine B", "Florentine C"])
    await expect(weapon).to_have_value("FLORENTINE")
    await page.get_by_role("button", name="Retry results", exact=True).focus()
    fixture.fail_metadata = False
    await page.keyboard.press("Enter")
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
        await expect(weapon).to_have_value("FLORENTINE")
        old_release.set()
        await asyncio.wait_for(old_delivered.wait(), TIMEOUT_MS / 1000)
        await page.evaluate("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
        await expect(breaks.locator("tbody tr")).to_have_count(0)
        new_release.set()
        await assert_players(breaks, ["Florentine A", "Florentine B", "Florentine C"][:public_limit])

    fixture.hidden = True
    await expect(page.get_by_text("Results are not being shown for this side competition.", exact=True)).to_be_visible()
    await expect(page.locator(".sidecomp-standings-table")).to_have_count(0)
    await page.set_viewport_size({"width": 390, "height": 900})


async def verify_weapon_choices(check: SmokeCheck, page: Page, fixture: StandingsFixture) -> None:
    for _, release, _ in fixture.held_policies.values():
        release.set()
    fixture.held_policies.clear()
    fixture.hidden = False
    fixture.generic = True
    fixture.show_all = True
    fixture.public_limit = 8
    await page.goto(f"{check.base_url}/demo-open/sidecomps/{fixture.comp_id}/results")
    section = page.get_by_role("region", name="Standings", exact=True)
    weapon = section.get_by_role("combobox", name="Weapon", exact=True)
    await expect(weapon.locator("option")).to_have_text(["All weapons", *WEAPONS.values()])
    await expect(section.locator("tbody tr")).to_have_count(8)
    await expect(section.get_by_role("button", name="Win %", exact=True)).to_be_visible()
    await expect(section.locator('th[aria-sort="descending"]')).to_have_text("Win %↓")
    await expect(section.locator("thead th")).to_have_count(5)

    for value, label in WEAPONS.items():
        await weapon.select_option(value)
        expected_name = {"CHAIN": LONG_NAME, "LONG": UNBROKEN_NAME}.get(value, f"{label} Player")
        await assert_players(section, [expected_name])
        await expect(section.locator(".sidecomp-standing-weapon")).to_have_text(label)
    await expect(section.locator("tbody td:last-child")).to_have_text("—")

    # Native select keyboard behavior keeps all options reachable without a pointer.
    await page.keyboard.press("Tab")
    await check_keyboard_focus(weapon)
    await page.keyboard.press("Home")
    await expect(weapon).to_have_value("")
    await expect(section.locator("tbody tr")).to_have_count(8)
    await page.keyboard.press("End")
    await expect(weapon).to_have_value("UNARMED")
    await assert_players(section, ["Unarmed Player"])
    await page.keyboard.press("Home")
    await page.keyboard.press("ArrowDown")
    await expect(weapon).to_have_value("CHAIN")
    await assert_players(section, [LONG_NAME])
    await page.keyboard.press("Tab")
    # The standings scroll region is intentionally a keyboard tab stop.
    await expect(section.get_by_role("region", name="Standings standings", exact=True)).to_be_focused()
    await page.keyboard.press("Tab")
    wins = section.get_by_role("button", name="Wins", exact=True)
    await expect(wins).to_be_focused()
    await check_keyboard_focus(wins)
    await page.keyboard.press("Enter")
    await expect(section.locator('th[aria-sort="descending"]')).to_have_text("Wins↓")
    await weapon.select_option("")
    await expect(section.locator("tbody tr")).to_have_count(8)
    for width in (320, 390, 1280):
        await page.set_viewport_size({"width": width, "height": 900})
        await page.evaluate("window.scrollTo(0, 0); document.activeElement?.blur()")
        await check_table_layout(page)
        await check.check_layout(page, "sidecomp-all-weapons", width)
        check.visited += 1

    # Polling removes an unavailable option and restores the complete table.
    await weapon.select_option("SKULL")
    await assert_players(section, ["Skull Player"])
    fixture.removed_weapon = "SKULL"
    await expect(weapon.locator('option[value="SKULL"]')).to_have_count(0)
    await expect(weapon).to_have_value("")
    await expect(section.locator("tbody tr")).to_have_count(7)
    fixture.removed_weapon = None
    await expect(weapon.locator("option")).to_have_count(9)
    await expect(section.locator("tbody tr")).to_have_count(8)
    await page.set_viewport_size({"width": 390, "height": 900})


async def verify_appearance(check: SmokeCheck, page: Page) -> None:
    section = page.get_by_role("region", name="Standings", exact=True)
    weapon = section.get_by_role("combobox", name="Weapon", exact=True)
    for palette in PALETTES:
        for mode in ("light", "dark"):
            await choose(page, palette, mode)
            await preference(page, palette, mode)
            await close_menu(page)
            await page.keyboard.press("Tab")
            await check_keyboard_focus(weapon)
            await check_keyboard_focus(section.get_by_role("button", name="Wins", exact=True))
            await check_contrast(
                page,
                ".sidecomp-weapon-filter label, .sidecomp-weapon-filter select, "
                ".sidecomp-standings-table th, .sidecomp-standings-table .fw-semibold, "
                ".sidecomp-standings-table .text-muted, .sidecomp-standings-table .table-number",
            )
            await check_table_layout(page)
            await page.evaluate("window.scrollTo(0, 0); document.activeElement?.blur()")
            await check.check_layout(page, f"sidecomp-{palette}-{mode}", 390)
            check.visited += 1


async def verify_large_values(check: SmokeCheck, page: Page, fixture: StandingsFixture) -> None:
    """Unusually large counts use the accessible table scroll region."""
    section = page.get_by_role("region", name="Standings", exact=True)
    fixture.large_numbers = True
    try:
        await expect(section.locator("tbody tr:first-child td:first-child")).to_have_text("2147483601")
        await expect(section.locator("tbody tr:first-child td:nth-child(3)")).to_have_text("2147483647")
        for width in (320, 390, 1280):
            await page.set_viewport_size({"width": width, "height": 900})
            await check_table_layout(page, allow_horizontal_scroll=True)
            wrapper = section.get_by_role("region", name="Standings standings", exact=True)
            await expect(wrapper).to_have_attribute("tabindex", "0")
            assert await wrapper.evaluate("el => getComputedStyle(el).overflowX") == "auto"
            await check.check_layout(page, "sidecomp-large-values", width)
            check.visited += 1
    finally:
        fixture.large_numbers = False
        await page.set_viewport_size({"width": 390, "height": 900})
    await expect(section.locator("tbody tr:first-child td:first-child")).to_have_text("1")


async def verify_large_text(check: SmokeCheck, page: Page) -> None:
    """Check the standings at 200% text size independently of the shared header."""
    await page.set_viewport_size({"width": 320, "height": 900})
    await page.evaluate("document.documentElement.style.fontSize = '200%'")
    try:
        await check_table_layout(page, allow_horizontal_scroll=True)
        section = page.get_by_role("region", name="Standings", exact=True)
        bounds = await section.bounding_box()
        assert bounds and bounds["x"] >= -1 and bounds["x"] + bounds["width"] <= 321, bounds
        if check.screenshots:
            await section.screenshot(path=str(check.screenshots / "0320-sidecomp-enlarged-text.png"))
        check.visited += 1
    finally:
        await page.evaluate("document.documentElement.style.removeProperty('font-size')")
        await page.set_viewport_size({"width": 390, "height": 900})


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
            await check.workflow(
                page, "sidecomp-weapon-choices", 390, lambda: verify_weapon_choices(check, page, fixture)
            )
            await check.workflow(page, "sidecomp-appearance", 390, lambda: verify_appearance(check, page))
            await check.workflow(
                page, "sidecomp-large-number-regression", 390, lambda: verify_large_values(check, page, fixture)
            )
            await check.workflow(page, "sidecomp-large-text", 390, lambda: verify_large_text(check, page))
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
