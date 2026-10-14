use crate::components::Markdown;
use dioxus::prelude::*;

#[component]
pub fn Developers() -> Element {
    rsx! {
        Markdown { page: "developers" }
    }
}
