use crate::types::RegistrationFormConfig;
use dioxus::prelude::*;

#[component]
pub fn RegistrationFormNotice(config: RegistrationFormConfig, username: Option<String>) -> Element {
    if !config.registration_form_required {
        return rsx! {};
    }

    rsx! {
        div { class: "alert alert-info mb-3",
            h3 { class: "h6", "Registration form required" }
            p { class: "mb-2",
                if let Some(username) = username {
                    "Complete the form using your Arctos username: "
                    strong { "@{username}" }
                    "."
                } else {
                    "The player must complete the form using their Arctos username."
                }
                " Arctos checks for a response before confirming registration."
            }
            if let Some(url) = config.registration_form_url {
                a { href: url, target: "_blank", rel: "noopener noreferrer",
                    "Open registration form (opens in a new tab)"
                }
            }
        }
    }
}

#[component]
pub fn RegistrationFormSettings(
    mut draft: Signal<RegistrationFormConfig>,
    disabled: bool,
) -> Element {
    let config = draft.read().clone();
    rsx! {
        fieldset { class: "mb-4", disabled,
            legend { class: "h5", "Registration form" }
            div { class: "form-check mb-2",
                input {
                    class: "form-check-input", r#type: "checkbox",
                    id: "registration_form_required",
                    checked: config.registration_form_required,
                    aria_describedby: "registration-form-help",
                    onchange: move |event| draft.write().registration_form_required = event.checked(),
                }
                label { class: "form-check-label", r#for: "registration_form_required",
                    "Require a Google Form response for player registration"
                }
            }
            p { id: "registration-form-help", class: "form-text",
                "Players complete the form with their exact Arctos username. Existing confirmed registrations remain valid."
            }
            if config.registration_form_required {
                if !config.registration_form_available {
                    p { class: "alert alert-warning",
                        "Form verification is unavailable. Contact the site administrator to configure Google Sheets access."
                    }
                }
                div { class: "mb-3",
                    label { class: "form-label", r#for: "registration_form_url", "Google Form link" }
                    input {
                        class: "form-control", r#type: "url", id: "registration_form_url", required: true,
                        aria_describedby: "registration-form-url-help",
                        value: config.registration_form_url.unwrap_or_default(),
                        oninput: move |event| draft.write().registration_form_url = Some(event.value()),
                    }
                    div { id: "registration-form-url-help", class: "form-text",
                        "Use the responder link that players open to complete the form."
                    }
                }
                div { class: "mb-3",
                    label { class: "form-label", r#for: "registration_form_sheet_url", "Response spreadsheet link" }
                    input {
                        class: "form-control", r#type: "url", id: "registration_form_sheet_url", required: true,
                        aria_describedby: "registration-form-sheet-help",
                        value: config.registration_form_sheet_url.unwrap_or_default(),
                        oninput: move |event| draft.write().registration_form_sheet_url = Some(event.value()),
                    }
                    div { id: "registration-form-sheet-help", class: "form-text",
                        "Open the response tab in Google Sheets and copy its link. This link is visible only to organizers."
                        if let Some(email) = config.registration_form_service_account_email {
                            p { class: "mb-0 mt-1",
                                "Share the spreadsheet with "
                                strong { style: "overflow-wrap: anywhere;", "{email}" }
                                " as a Viewer. Keep general access Restricted."
                            }
                        }
                    }
                }
                div { class: "mb-3",
                    label { class: "form-label", r#for: "registration_form_username_column", "Username column heading" }
                    input {
                        class: "form-control", r#type: "text", id: "registration_form_username_column", required: true,
                        aria_describedby: "registration-form-column-help",
                        value: config.registration_form_username_column.unwrap_or_default(),
                        oninput: move |event| draft.write().registration_form_username_column = Some(event.value()),
                    }
                    div { id: "registration-form-column-help", class: "form-text",
                        "Copy the column heading from the first row. The form must ask for the player's Arctos username with matching capitalization. A leading @ is optional."
                    }
                }
                p { class: "form-text mb-0", "Saving settings checks spreadsheet access and the username column." }
            }
        }
    }
}
