//! Shared team chip: avatar and name, or a tag / match-reference / empty slot.
//!
//! Concrete teams link to their profile. Tags and winner/loser references keep
//! the icon treatment used on the schedule. An empty or TBA slot says
//! "no team entered" with an error icon.

use crate::Route;
use crate::api;
use crate::display::short_or_truncate;
use dioxus::prelude::*;

/// Full pseudonym, or the registration shortname when the layout is tight.
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum TeamLabelStyle {
    Full,
    Short,
}

/// One team, ref, tag, or reference slot.
#[derive(Clone, Debug, PartialEq)]
pub struct TeamSlot {
    /// Raw token: team id, `tag::Name`, `Match::winner`, `TBA`, or display text.
    pub token: String,
    /// Set when this slot is a concrete team.
    pub team_id: Option<String>,
    /// Full pseudonym when known.
    pub name: Option<String>,
    pub shortname: Option<String>,
    pub photo: Option<String>,
}

impl TeamSlot {
    /// Human-readable label for tooltips (full name, tag, or reference).
    pub fn full_label(&self) -> String {
        match classify(self) {
            SlotKind::Team => self
                .name
                .as_deref()
                .map(str::trim)
                .filter(|s| !s.is_empty())
                .unwrap_or(self.token.as_str())
                .to_string(),
            SlotKind::Tag { label } | SlotKind::Reference { label } => label,
            SlotKind::Missing => "no team entered".to_string(),
        }
    }
}

enum SlotKind {
    Team,
    Tag { label: String },
    Reference { label: String },
    Missing,
}

fn nonempty(value: Option<&str>) -> Option<&str> {
    value.map(str::trim).filter(|s| !s.is_empty())
}

fn classify(slot: &TeamSlot) -> SlotKind {
    if nonempty(slot.team_id.as_deref()).is_some() {
        return SlotKind::Team;
    }
    let raw = nonempty(Some(slot.token.as_str()))
        .or_else(|| nonempty(slot.name.as_deref()))
        .unwrap_or("");
    if raw.is_empty() || is_missing_label(raw) {
        return SlotKind::Missing;
    }
    if let Some(label) = tag_label(raw) {
        return SlotKind::Tag { label };
    }
    if let Some(label) = reference_label(raw) {
        return SlotKind::Reference { label };
    }
    SlotKind::Team
}

fn is_missing_label(raw: &str) -> bool {
    raw.eq_ignore_ascii_case("tba")
        || raw.eq_ignore_ascii_case("tbd")
        || raw == "-"
        || raw == "—"
        || raw == "Team 1"
        || raw == "Team 2"
}

fn tag_label(raw: &str) -> Option<String> {
    let rest = raw.get(5..)?;
    if raw.get(..5)?.eq_ignore_ascii_case("tag::") {
        Some(rest.trim().to_string())
    } else {
        None
    }
}

fn reference_label(raw: &str) -> Option<String> {
    if let Some(name) = raw.strip_suffix("::winner") {
        return Some(format!("{} winner", name.trim()));
    }
    if let Some(name) = raw.strip_suffix("::loser") {
        return Some(format!("{} loser", name.trim()));
    }
    if raw.ends_with(" winner") || raw.ends_with(" loser") {
        return Some(raw.to_string());
    }
    None
}

fn shown_team_name(slot: &TeamSlot, label_style: TeamLabelStyle) -> String {
    let full = nonempty(slot.name.as_deref())
        .unwrap_or(slot.token.as_str())
        .to_string();
    match label_style {
        TeamLabelStyle::Full => full,
        TeamLabelStyle::Short => short_or_truncate(&full, slot.shortname.as_deref()),
    }
}

const ICON_STYLE: &str = "width:1em;height:1em;object-fit:contain;flex-shrink:0;filter:invert(27%) sepia(98%) saturate(2476%) hue-rotate(226deg) brightness(99%) contrast(101%);";

fn kind_icon(src_file: &str, alt: &str) -> Element {
    let base = api::base_url();
    let src = format!("{base}/static/{src_file}");
    rsx! {
        img { class: "team-label-icon", style: "{ICON_STYLE}", src: "{src}", alt: "{alt}" }
    }
}

fn team_avatar(photo: Option<&str>, letter: char) -> Element {
    let base = api::base_url();
    if let Some(ph) = nonempty(photo) {
        let src = format!("{base}/static/{ph}");
        rsx! {
            img {
                class: "rounded-circle",
                style: "width:1.25em;height:1.25em;object-fit:cover;flex-shrink:0;",
                src: "{src}",
                alt: "",
            }
        }
    } else {
        rsx! {
            span {
                class: "rounded-circle d-inline-flex align-items-center justify-content-center",
                style: "width:1.25em;height:1.25em;font-size:0.7em;background:#6c757d;color:white;flex-shrink:0;",
                "{letter}"
            }
        }
    }
}

#[component]
pub fn TeamLabel(
    slot: TeamSlot,
    label_style: TeamLabelStyle,
    #[props(default)] stop_click: bool,
) -> Element {
    let stop = stop_click;
    match classify(&slot) {
        SlotKind::Missing => rsx! {
            span { class: "team-label d-inline-flex align-items-center gap-1 text-danger",
                i { class: "fa-solid fa-circle-exclamation", aria_hidden: "true" }
                span { "no team entered" }
            }
        },
        SlotKind::Tag { label } => rsx! {
            span { class: "team-label d-inline-flex align-items-center gap-1",
                {kind_icon("tag.svg", "Tag")}
                span { "{label}" }
            }
        },
        SlotKind::Reference { label } => rsx! {
            span { class: "team-label d-inline-flex align-items-center gap-1",
                {kind_icon("reference.svg", "Reference")}
                span { "{label}" }
            }
        },
        SlotKind::Team => {
            let shown = shown_team_name(&slot, label_style);
            let title = slot.full_label();
            let letter = shown.chars().next().unwrap_or('?');
            let photo = slot.photo.clone();
            let avatar = team_avatar(photo.as_deref(), letter);
            if let Some(id) = nonempty(slot.team_id.as_deref()).map(|s| s.to_string()) {
                rsx! {
                    span {
                        class: "d-inline-flex",
                        onclick: move |ev: Event<MouseData>| {
                            if stop {
                                ev.stop_propagation();
                            }
                        },
                        onpointerdown: move |ev: Event<PointerData>| {
                            if stop {
                                ev.stop_propagation();
                            }
                        },
                        Link {
                            to: Route::TeamProfilePage { id },
                            class: "team-label text-decoration-none d-inline-flex align-items-center gap-1",
                            title: "{title}",
                            {avatar}
                            span { "{shown}" }
                        }
                    }
                }
            } else {
                rsx! {
                    span { class: "team-label d-inline-flex align-items-center gap-1", title: "{title}",
                        {avatar}
                        span { "{shown}" }
                    }
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn slot(token: &str, team_id: Option<&str>, name: Option<&str>) -> TeamSlot {
        TeamSlot {
            token: token.to_string(),
            team_id: team_id.map(|s| s.to_string()),
            name: name.map(|s| s.to_string()),
            shortname: None,
            photo: None,
        }
    }

    #[test]
    fn missing_when_tba_or_blank() {
        assert!(matches!(classify(&slot("", None, None)), SlotKind::Missing));
        assert!(matches!(classify(&slot("TBA", None, None)), SlotKind::Missing));
        assert!(matches!(classify(&slot("tba", None, Some("TBA"))), SlotKind::Missing));
        assert!(matches!(classify(&slot("Team 1", None, None)), SlotKind::Missing));
    }

    #[test]
    fn tag_and_reference_keep_their_labels() {
        match classify(&slot("tag::Pool A", None, None)) {
            SlotKind::Tag { label } => assert_eq!(label, "Pool A"),
            other => panic!("expected tag, got {}", kind_name(&other)),
        }
        match classify(&slot("Semifinal::winner", None, None)) {
            SlotKind::Reference { label } => assert_eq!(label, "Semifinal winner"),
            other => panic!("expected reference, got {}", kind_name(&other)),
        }
        match classify(&slot("Final loser", None, None)) {
            SlotKind::Reference { label } => assert_eq!(label, "Final loser"),
            other => panic!("expected reference, got {}", kind_name(&other)),
        }
    }

    #[test]
    fn concrete_team_wins_over_a_tba_name() {
        assert!(matches!(
            classify(&slot("TBA", Some("team-1"), Some("TBA"))),
            SlotKind::Team
        ));
    }

    fn kind_name(kind: &SlotKind) -> &'static str {
        match kind {
            SlotKind::Team => "team",
            SlotKind::Tag { .. } => "tag",
            SlotKind::Reference { .. } => "reference",
            SlotKind::Missing => "missing",
        }
    }
}
