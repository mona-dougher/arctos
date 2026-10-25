use crate::Route;
use crate::api;
use crate::components::{ALL_POMPFEN, PompfenIcon};
use crate::types::{SideCompStandingRow, SideCompStandingTable};
use dioxus::prelude::*;
#[cfg(target_arch = "wasm32")]
use gloo_timers::callback::Interval;
use std::cmp::Ordering;

#[derive(Clone, Copy, PartialEq, Eq)]
enum StandingSort {
    Wins,
    WinRatio,
}

fn ordered_standings(rows: &[SideCompStandingRow], sort: StandingSort) -> Vec<SideCompStandingRow> {
    let mut ordered = rows.to_vec();
    ordered.sort_by(|left, right| match sort {
        StandingSort::Wins => wins_order(left, right),
        StandingSort::WinRatio => win_ratio_order(left, right),
    });
    for (index, row) in ordered.iter_mut().enumerate() {
        row.rank = (index as i32) + 1;
    }
    ordered
}

fn wins_order(left: &SideCompStandingRow, right: &SideCompStandingRow) -> Ordering {
    right
        .wins
        .cmp(&left.wins)
        .then_with(|| left.entry_number.cmp(&right.entry_number))
        .then_with(|| left.registration_id.cmp(&right.registration_id))
}

fn win_ratio_order(left: &SideCompStandingRow, right: &SideCompStandingRow) -> Ordering {
    let left_games = left.wins + left.losses.unwrap_or(0);
    let right_games = right.wins + right.losses.unwrap_or(0);
    match (left_games <= 0, right_games <= 0) {
        (true, false) => return Ordering::Greater,
        (false, true) => return Ordering::Less,
        (false, false) => {
            let left_ratio = left.wins as f64 / left_games as f64;
            let right_ratio = right.wins as f64 / right_games as f64;
            match right_ratio.partial_cmp(&left_ratio).unwrap_or(Ordering::Equal) {
                Ordering::Equal => {}
                order => return order,
            }
            match right.wins.cmp(&left.wins) {
                Ordering::Equal => {}
                order => return order,
            }
        }
        (true, true) => {}
    }
    left.entry_number
        .cmp(&right.entry_number)
        .then_with(|| left.registration_id.cmp(&right.registration_id))
}

#[component]
fn StandingSortHeader(label: &'static str, active: bool, onsort: EventHandler<()>) -> Element {
    rsx! {
        th {
            scope: "col",
            aria_sort: if active { "descending" } else { "none" },
            button {
                r#type: "button",
                class: if active {
                    "btn btn-link p-0 align-baseline text-decoration-none fw-bold"
                } else {
                    "btn btn-link p-0 align-baseline text-decoration-none fw-normal"
                },
                style: "color: inherit;",
                onclick: move |_| onsort.call(()),
                "{label}"
            }
        }
    }
}

fn photo_src(path: &Option<String>) -> Option<String> {
    path.as_ref()
        .map(|p| format!("{}/static/{}", api::base_url(), p))
}

#[component]
fn StandingAvatar(photo: Option<String>, is_team: bool) -> Element {
    if let Some(src) = photo_src(&photo) {
        rsx! {
            img {
                src: "{src}",
                alt: "",
                class: "rounded-circle me-2",
                style: "width: 28px; height: 28px; object-fit: cover;",
            }
        }
    } else {
        let icon = if is_team {
            "fas fa-users"
        } else {
            "fas fa-user"
        };
        rsx! {
            span {
                class: "d-inline-flex align-items-center justify-content-center bg-secondary rounded-circle text-white me-2",
                style: "width: 28px; height: 28px;",
                i { class: "{icon}", style: "font-size: 0.75rem;" }
            }
        }
    }
}

#[component]
fn StandingsTableView(table: SideCompStandingTable) -> Element {
    let mut weapon_filter = use_signal(|| None::<String>);
    let track_losses = table.track_losses;
    let mut sort_by = use_signal(move || {
        if track_losses {
            StandingSort::WinRatio
        } else {
            StandingSort::Wins
        }
    });
    let rows = table.rows.clone();
    let sort = if track_losses && sort_by() == StandingSort::WinRatio {
        StandingSort::WinRatio
    } else {
        StandingSort::Wins
    };
    let ordered = ordered_standings(&rows, sort);
    let filtered: Vec<SideCompStandingRow> = match weapon_filter() {
        None => ordered,
        Some(w) => ordered
            .into_iter()
            .filter(|r| r.weapon.as_deref() == Some(w.as_str()))
            .collect(),
    };
    let weapons_in_table: Vec<String> = {
        let mut seen = Vec::new();
        for r in rows.iter() {
            if let Some(w) = r.weapon.as_ref() {
                if !seen.iter().any(|s: &String| s == w) {
                    seen.push(w.clone());
                }
            }
        }
        // Keep stable pompfen order
        seen.sort_by_key(|w| {
            ALL_POMPFEN
                .iter()
                .position(|p| p.id == w)
                .unwrap_or(usize::MAX)
        });
        seen
    };

    rsx! {
        div { class: "mb-4",
            div { class: "d-flex flex-wrap align-items-center justify-content-between gap-2 mb-2",
                h3 { class: "h4 mb-0", "{table.title}" }
                div { class: "d-flex flex-wrap gap-1",
                    button {
                        class: if weapon_filter().is_none() { "btn btn-sm btn-primary" } else { "btn btn-sm btn-outline-secondary" },
                        onclick: move |_| weapon_filter.set(None),
                        "All"
                    }
                    for w in weapons_in_table.iter() {
                        {
                            let wid = w.clone();
                            let wid_btn = w.clone();
                            let active = weapon_filter().as_deref() == Some(wid.as_str());
                            rsx! {
                                button {
                                    class: if active { "btn btn-sm btn-primary d-inline-flex align-items-center gap-1" } else { "btn btn-sm btn-outline-secondary d-inline-flex align-items-center gap-1" },
                                    onclick: move |_| weapon_filter.set(Some(wid_btn.clone())),
                                    PompfenIcon { weapon: wid.clone(), size: "1.1em".to_string() }
                                    "{wid}"
                                }
                            }
                        }
                    }
                }
            }
            if filtered.is_empty() {
                p { class: "text-muted", "No players to show." }
            } else {
                div { class: "table-responsive",
                    table { class: "table table-striped align-middle",
                        thead {
                            tr {
                                th { "Rank" }
                                th { "#" }
                                th { "Player" }
                                th { "Role" }
                                StandingSortHeader {
                                    label: "Wins",
                                    active: sort == StandingSort::Wins,
                                    onsort: move |_| sort_by.set(StandingSort::Wins),
                                }
                                if table.track_losses {
                                    th { "Losses" }
                                    StandingSortHeader {
                                        label: "Win %",
                                        active: sort == StandingSort::WinRatio,
                                        onsort: move |_| sort_by.set(StandingSort::WinRatio),
                                    }
                                }
                            }
                        }
                        tbody {
                            for row in filtered.iter() {
                                tr { key: "{row.registration_id}",
                                    td { "{row.rank}" }
                                    td { "{row.entry_number}" }
                                    td {
                                        div { class: "d-flex align-items-center",
                                            StandingAvatar { photo: row.profile_photo.clone(), is_team: false }
                                            div {
                                                div { class: "fw-semibold", "{row.display_name}" }
                                                div { class: "small text-muted d-flex align-items-center",
                                                    StandingAvatar { photo: row.team_profile_photo.clone(), is_team: true }
                                                    span {
                                                        {
                                                            let pseudo = row.jersey_name.clone().unwrap_or_else(|| "—".to_string());
                                                            let num = row.jersey_number.clone().unwrap_or_default();
                                                            let short = row.team_shortname.clone().unwrap_or_else(|| "merc".to_string());
                                                            if num.is_empty() {
                                                                format!("{pseudo} · {short}")
                                                            } else {
                                                                format!("{pseudo} ({num}) · {short}")
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                    td {
                                        if let Some(w) = row.weapon.as_ref() {
                                            PompfenIcon { weapon: w.clone(), size: "1.5em".to_string() }
                                        }
                                    }
                                    td { class: "fw-bold", "{row.wins}" }
                                    if table.track_losses {
                                        td { "{row.losses.unwrap_or(0)}" }
                                        td { class: "fw-bold",
                                            match row.win_percentage {
                                                Some(percentage) => format!("{percentage:.0}%"),
                                                None => "—".to_string(),
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

#[component]
pub fn SideCompResults(url: String, comp_id: i32) -> Element {
    let mut tick = use_signal(|| 0u32);
    let mut poll_started = use_signal(|| false);
    let standings = use_resource(move || {
        let _ = tick();
        async move { api::sidecomp_standings(comp_id).await }
    });

    use_effect(move || {
        #[cfg(target_arch = "wasm32")]
        if !poll_started() {
            let mut tick = tick;
            let handle = Interval::new(1000, move || {
                tick.set(tick().wrapping_add(1));
            });
            poll_started.set(true);
            std::mem::forget(handle);
        }
        #[cfg(not(target_arch = "wasm32"))]
        {
            let _ = (&tick, &poll_started);
        }
    });

    let url_back = url.clone();

    rsx! {
        div { class: "row",
            div { class: "col-12",
                Link {
                    to: Route::SideCompDetail { url: url_back, comp_id },
                    class: "btn btn-link",
                    "<- Back to side competition"
                }
                match standings.read().as_ref() {
                    Some(Ok(data)) => {
                        if !data.results_page_enabled {
                            rsx! {
                                div { class: "alert alert-secondary", "Results are not being shown for this side competition." }
                            }
                        } else {
                            let tables = data.tables.clone();
                            let name = data.name.clone();
                            let title = if data.finalized {
                                format!("{name} - Results (Final)")
                            } else {
                                format!("{name} - Results (Unofficial)")
                            };
                            rsx! {
                                h1 { "{title}" }
                                for table in tables.into_iter() {
                                    StandingsTableView { key: "{table.id}", table }
                                }
                            }
                        }
                    }
                    Some(Err(e)) => rsx! { div { class: "alert alert-danger", "{e}" } },
                    None => rsx! { div { class: "spinner-border" } },
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{ordered_standings, StandingSort};
    use crate::types::SideCompStandingRow;

    fn row(registration_id: i32, entry_number: i32, wins: i32, losses: Option<i32>) -> SideCompStandingRow {
        SideCompStandingRow {
            registration_id,
            entry_number,
            weapon: None,
            player_id: format!("p{registration_id}"),
            display_name: format!("Player {registration_id}"),
            profile_photo: None,
            jersey_name: None,
            jersey_number: None,
            team_shortname: None,
            team_profile_photo: None,
            wins,
            losses,
            win_percentage: None,
            rank: 0,
        }
    }

    #[test]
    fn win_ratio_sort_puts_unplayed_last_and_breaks_ties_by_wins() {
        let rows = vec![
            row(2, 2, 6, Some(2)),
            row(4, 4, 0, Some(0)),
            row(1, 1, 1, Some(0)),
            row(3, 3, 3, Some(1)),
        ];
        let ordered = ordered_standings(&rows, StandingSort::WinRatio);
        assert_eq!(
            ordered.iter().map(|standing| standing.registration_id).collect::<Vec<_>>(),
            vec![1, 2, 3, 4]
        );
        assert_eq!(ordered.iter().map(|standing| standing.rank).collect::<Vec<_>>(), vec![1, 2, 3, 4]);
    }

    #[test]
    fn wins_sort_is_descending_and_does_not_reverse() {
        let rows = vec![
            row(1, 10, 1, Some(0)),
            row(2, 2, 6, Some(2)),
            row(3, 3, 3, Some(1)),
            row(5, 4, 3, Some(0)),
            row(4, 8, 0, Some(0)),
        ];
        let ordered = ordered_standings(&rows, StandingSort::Wins);
        assert_eq!(
            ordered.iter().map(|standing| standing.registration_id).collect::<Vec<_>>(),
            vec![2, 3, 5, 1, 4]
        );
        let again = ordered_standings(&ordered, StandingSort::Wins);
        assert_eq!(
            again.iter().map(|standing| standing.registration_id).collect::<Vec<_>>(),
            vec![2, 3, 5, 1, 4]
        );
    }
}
