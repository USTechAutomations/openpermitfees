import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OFFER = ROOT / "offer.json"
README = ROOT / "README.md"
CONTACT_URL = (
    "https://github.com/USTechAutomations/openpermitfees/issues/new?"
    "template=commission-request.yml"
)


def test_offer_contract_pins_the_existing_public_offer():
    payload = json.loads(OFFER.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "usta.openpermitfees-offer.v1"
    assert payload["sku"] == "commissioned-jurisdiction"
    assert payload["status"] == "request_only"
    assert payload["price"] == {
        "amount_cents": 24_900,
        "currency": "USD",
        "cadence": "once",
    }
    assert payload["delivery"] == {
        "within_business_days": 10,
        "method": "pull request to the public repository",
        "license": "CC BY 4.0",
    }
    assert payload["request"]["url"] == CONTACT_URL
    assert payload["payment"] == {
        "checkout_armed": False,
        "human_sends_payment_link": True,
    }
    assert payload["attribution"] == {
        "path_id": "openpermitfees:commissioned-jurisdiction:contact",
        "hypothesis_id": "h-openpermitfees-commissioned-jurisdiction-2026-08",
        "artifact_id": "openpermitfees-readme-commission-offer",
        "job_id": "openpermitfees-contact-ingest",
    }


def test_readme_links_the_offer_contract_once():
    readme = README.read_text(encoding="utf-8")

    assert readme.count("[machine-readable offer contract](offer.json)") == 1
