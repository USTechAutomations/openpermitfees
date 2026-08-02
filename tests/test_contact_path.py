from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / ".github" / "ISSUE_TEMPLATE" / "commission-request.yml"
README = ROOT / "README.md"
CONTACT_URL = (
    "https://github.com/USTechAutomations/openpermitfees/issues/new?"
    "template=commission-request.yml"
)


def test_commission_cta_uses_the_project_owned_structured_form():
    readme = README.read_text(encoding="utf-8")

    assert readme.count(CONTACT_URL) == 1
    assert "partner?interest=openpermitfees" not in readme
    assert "replies in the issue the same working day" in readme


def test_commission_form_pins_the_public_intake_contract():
    form = FORM.read_text(encoding="utf-8")

    required_markers = (
        "name: Commission a Jurisdiction",
        'title: "[Commission Request] "',
        "  - commission-request",
        "id: jurisdiction",
        "label: Jurisdiction",
        "id: organization",
        "label: Organization or team",
        "id: use_case",
        "label: Intended use",
        "id: timing",
        "label: Preferred timing",
        "id: public_issue",
        "label: Public issue acknowledgement",
        "I understand this request is public and I have not included personal data, credentials, API keys, private documents, or other secrets.",
        "$249 one-time",
        "ten business days",
        "service fee paid to US Tech Automations, not a government charge",
    )
    assert all(marker in form for marker in required_markers)
    assert form.count("required: true") == 5
    assert all(
        forbidden not in form
        for forbidden in ("id: email", "id: phone", "id: payment")
    )
