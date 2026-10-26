use crate::api;
use crate::components::{pompfen_by_id, PompfenIcon};
use crate::types::{SideCompStandingTable, SideCompStandings};
use crate::Route;
use dioxus::prelude::*;
#[cfg(target_arch = "wasm32")]
use gloo_timers::future::TimeoutFuture;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum StandingSort {
    Wins,
    WinRatio,
}

impl StandingSort {
    fn default_for(track_losses: bool) -> Self {
        if track_losses {
            Self::WinRatio
        } else {
            Self::Wins
        }
    }
    fn query_value(self) -> &'static str {
        match self {
            Self::Wins => "wins",
            Self::WinRatio => "win_percentage",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct StandingSelection {
    weapon: Option<String>,
    sort: StandingSort,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct PublicationPolicy {
    showing_all_results: bool,
    public_limit: Option<i32>,
}

impl PublicationPolicy {
    fn from_standings(standings: &SideCompStandings) -> Self {
        Self {
            showing_all_results: standings.showing_all_results,
            public_limit: standings.only_show_top_n_results,
        }
    }
}

impl StandingSelection {
    fn is_default(&self, track_losses: bool) -> bool {
        self.weapon.is_none() && self.sort == StandingSort::default_for(track_losses)
    }
    fn for_loss_tracking(mut self, track_losses: bool) -> Self {
        if !track_losses {
            self.sort = StandingSort::Wins;
        }
        self
    }
}

#[component]
fn StandingSortHeader(label: &'static str, active: bool, onsort: EventHandler<()>) -> Element {
    rsx! {
        th {
            scope: "col",
            class: "table-number",
            aria_sort: if active { "descending" } else { "none" },
            button {
                r#type: "button",
                class: if active { "btn btn-link p-0 align-baseline text-decoration-none fw-bold" } else { "btn btn-link p-0 align-baseline text-decoration-none fw-normal" },
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
fn StandingsTableView(
    comp_id: i32,
    table: SideCompStandingTable,
    publication_policy: PublicationPolicy,
) -> Element {
    let track_losses = table.track_losses;
    let mut selection = use_signal(move || StandingSelection {
        weapon: None,
        sort: StandingSort::default_for(track_losses),
    });
    let current_selection = selection().for_loss_tracking(track_losses);
    let sort = current_selection.sort;
    let mut selected_standings = use_resource(use_reactive(
        &(comp_id, table.id.clone(), track_losses, publication_policy),
        move |(comp_id, table_id, track_losses, publication_policy)| {
            let selected = selection().for_loss_tracking(track_losses);
            async move {
                // The page refresh already supplies the default table.
                if selected.is_default(track_losses) {
                    return (selected, publication_policy, Ok(None));
                }
                let result = api::sidecomp_standings(
                    comp_id,
                    Some(&table_id),
                    selected.weapon.as_deref(),
                    Some(selected.sort.query_value()),
                )
                .await;
                let response_policy = result
                    .as_ref()
                    .map(PublicationPolicy::from_standings)
                    .unwrap_or(publication_policy);
                let result = result.and_then(|data| {
                    if !data.results_page_enabled {
                        return Err(
                            "Results are not being shown for this side competition.".to_string()
                        );
                    }
                    data.tables
                        .into_iter()
                        .find(|table| table.id == table_id)
                        .map(Some)
                        .ok_or_else(|| "The standings table is unavailable.".to_string())
                });
                (selected, response_policy, result)
            }
        },
    ));
    use_future(move || async move {
        #[cfg(target_arch = "wasm32")]
        loop {
            TimeoutFuture::new(1000).await;
            if selected_standings.finished() {
                selected_standings.restart();
            }
        }
    });
    // A changed selection or publication policy invalidates the previous rows.
    let displayed_table = if current_selection.is_default(track_losses) {
        Some(Ok(table.clone()))
    } else {
        match selected_standings.read().as_ref() {
            Some((loaded_selection, response_policy, result))
                if loaded_selection == &current_selection
                    && response_policy == &publication_policy =>
            {
                result.clone().transpose()
            }
            _ => None,
        }
    };
    let rows = match &displayed_table {
        Some(Ok(loaded)) => loaded.rows.clone(),
        _ => Vec::new(),
    };
    let weapon_name = current_selection.weapon.as_ref().map(|id| {
        pompfen_by_id(id)
            .map_or(id.as_str(), |option| option.label)
            .to_string()
    });
    rsx! {
        section { class: "mb-4", aria_label: "{table.title}",
            div { class: "d-flex flex-wrap align-items-center justify-content-between gap-2 mb-2",
                h3 { class: "h4 mb-0", "{table.title}" }
                div {
                    class: "d-flex flex-wrap gap-1",
                    role: "group",
                    aria_label: "{table.title} weapon filter",
                    button {
                        r#type: "button",
                        class: if current_selection.weapon.is_none() { "btn btn-sm btn-primary" } else { "btn btn-sm btn-outline-secondary" },
                        aria_pressed: current_selection.weapon.is_none(),
                        onclick: move |_| { selection.write().weapon = None; },
                        "All"
                    }
                    for w in table.available_weapons.iter() {
                        {
                            let wid = w.clone();
                            let wid_btn = w.clone();
                            let active = current_selection.weapon.as_deref() == Some(wid.as_str());
                            let label = pompfen_by_id(&wid)
                                .map_or(wid.as_str(), |option| option.label)
                                .to_string();
                            rsx! {
                                button {
                                    r#type: "button",
                                    class: if active { "btn btn-sm btn-primary d-inline-flex align-items-center gap-1" } else { "btn btn-sm btn-outline-secondary d-inline-flex align-items-center gap-1" },
                                    aria_pressed: active,
                                    onclick: move |_| { selection.write().weapon = Some(wid_btn.clone()); },
                                    span { aria_hidden: "true",
                                        PompfenIcon { weapon: wid.clone(), size: "1.1em".to_string() }
                                    }
                                    "{label}"
                                }
                            }
                        }
                    }
                }
            }
            p { class: "small text-muted mb-2",
                if let Some(weapon) = weapon_name {
                    "{weapon} · "
                } else {
                    "All weapons · "
                }
                if sort == StandingSort::WinRatio {
                    "Ranked by win percentage"
                } else {
                    "Ranked by wins"
                }
            }
            if displayed_table.is_none() {
                p { role: "status", class: "text-muted", "Loading standings…" }
            }
            if let Some(Err(error)) = &displayed_table {
                div { role: "alert", class: "alert alert-danger",
                    p { class: "mb-2", "Could not load standings: {error}" }
                    button {
                        r#type: "button",
                        class: "btn btn-outline-secondary",
                        onclick: move |_| selected_standings.restart(),
                        "Retry standings"
                    }
                }
            }
            if matches!(&displayed_table, Some(Ok(_))) && rows.is_empty() {
                p { class: "text-muted", "No players match this weapon." }
            }
            div {
                class: "table-responsive",
                role: "region",
                "aria-label": "{table.title} standings",
                tabindex: "0",
                table { class: "table table-striped align-middle sidecomp-standings-table",
                    thead {
                        tr {
                            th { scope: "col", class: "table-number", "Rank" }
                            th { scope: "col", class: "table-number", "#" }
                            th { scope: "col", class: "table-nowrap", "Player" }
                            th { scope: "col", class: "table-nowrap", "Role" }
                            StandingSortHeader {
                                label: "Wins",
                                active: sort == StandingSort::Wins,
                                onsort: move |_| { selection.write().sort = StandingSort::Wins; },
                            }
                            if table.track_losses {
                                th { scope: "col", class: "table-number", "Losses" }
                                StandingSortHeader {
                                    label: "Win %",
                                    active: sort == StandingSort::WinRatio,
                                    onsort: move |_| { selection.write().sort = StandingSort::WinRatio; },
                                }
                            }
                        }
                    }
                    tbody {
                        for row in rows.iter() {
                            tr { key: "{row.registration_id}",
                                td { class: "table-number", "{row.rank}" }
                                td { class: "table-number", "{row.entry_number}" }
                                td { class: "table-copy",
                                    div { class: "d-flex align-items-center",
                                        StandingAvatar {
                                            photo: row.profile_photo.clone(),
                                            is_team: false,
                                        }
                                        div {
                                            div { class: "fw-semibold", "{row.display_name}" }
                                            div { class: "small text-muted d-flex align-items-center",
                                                StandingAvatar {
                                                    photo: row.team_profile_photo.clone(),
                                                    is_team: true,
                                                }
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
                                td { class: "table-nowrap",
                                    if let Some(w) = row.weapon.as_ref() {
                                        PompfenIcon {
                                            weapon: w.clone(),
                                            size: "1.5em".to_string(),
                                        }
                                    }
                                }
                                td { class: "table-number fw-bold", "{row.wins}" }
                                if table.track_losses {
                                    td { class: "table-number", "{row.losses.unwrap_or(0)}" }
                                    td { class: "table-number fw-bold",
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

#[component]
pub fn SideCompResults(url: String, comp_id: i32) -> Element {
    let mut standings = use_resource(use_reactive(&comp_id, move |comp_id| async move {
        api::sidecomp_standings(comp_id, None, None, None).await
    }));
    let mut last_standings = use_signal(|| None::<SideCompStandings>);
    use_effect(move || {
        if let Some(Ok(data)) = standings.read().as_ref() {
            last_standings.set(Some(data.clone()));
        }
    });
    use_future(move || async move {
        #[cfg(target_arch = "wasm32")]
        loop {
            TimeoutFuture::new(1000).await;
            if standings.finished() {
                standings.restart();
            }
        }
    });
    let url_back = url.clone();
    let displayed_standings = last_standings().filter(|data| data.id == comp_id);
    rsx! {
        div { class: "row",
            div { class: "col-12",
                Link {
                    to: Route::SideCompDetail {
                        url: url_back,
                        comp_id,
                    },
                    class: "btn btn-link",
                    "<- Back to side competition"
                }
                if let Some(Err(error)) = standings.read().as_ref() {
                    div { class: "alert alert-danger", role: "alert",
                        p { class: "mb-2", "Could not refresh results: {error}" }
                        button {
                            r#type: "button",
                            class: "btn btn-outline-secondary",
                            onclick: move |_| standings.restart(),
                            "Retry results"
                        }
                    }
                }
                match displayed_standings {
                    Some(data) => {
                        if !data.results_page_enabled {
                            rsx! {
                                div { class: "alert alert-secondary", "Results are not being shown for this side competition." }
                            }
                        } else {
                            let publication_policy = PublicationPolicy::from_standings(&data);
                            let tables = data.tables.clone();
                            let name = data.name.clone();
                            let title = if data.finalized {
                                format!("{name} - Results (Final)")
                            } else {
                                format!("{name} - Results (Unofficial)")
                            };
                            rsx! {
                                h2 { "{title}" }
                                p { class: "text-muted",
                                    if data.showing_all_results {
                                        if data.only_show_top_n_results.is_some() {
                                            "You can view all results as an organizer. Public results are limited to the top {data.only_show_top_n_results.unwrap_or(0)} for each weapon and ranking."
                                        } else {
                                            "All results are public. Filter by weapon or choose a ranking column."
                                        }
                                    } else if let Some(limit) = data.only_show_top_n_results {
                                        "The organizer publishes the top {limit} results for each weapon and ranking. Choose a weapon to see its leaders."
                                    }
                                }
                                for table in tables.into_iter() {
                                    StandingsTableView {
                                        key: "{table.id}",
                                        comp_id,
                                        table,
                                        publication_policy,
                                    }
                                }
                            }
                        }
                    }
                    None => rsx! {
                        if !matches!(standings.read().as_ref(), Some(Err(_))) {
                            p { role: "status", "Loading results…" }
                        }
                    },
                }
            }
        }
    }
}
