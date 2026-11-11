import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.ai_investigation.provider import InvestigationProviderError
from app.ai_investigation.schemas import LLMInvestigationResponse
from app.ai_investigation.service import (
    InvestigationCaseNotFound,
    InvestigationRunError,
    InvestigationService,
)
from app.core.config import Settings
from app.models import (
    InvestigationReportRecord,
    MerchantOrder,
    ReconciliationExceptionRecord,
)

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
CASE_ID = "recon_0123456789abcdef0123"


class SequenceProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> LLMInvestigationResponse:
        self.prompts.append(prompt)
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        OLLAMA_MODEL="unit-test-model",
        INVESTIGATION_MISSING_PAYMENT_MINUTES=15,
    )


def _seed_case(session):
    session.add(
        ReconciliationExceptionRecord(
            case_id=CASE_ID,
            exception_type="MISSING_PAYMENT",
            severity="HIGH",
            merchant_order_id="MERCHANT-REF-1",
            paypal_order_id="PAYPAL-ORDER-1",
            capture_id=None,
            expected_value="25.50",
            actual_value=None,
            evidence_identifiers=["MERCHANT-REF-1"],
            explanation="Synthetic missing payment.",
            case_status="open",
            detected_at=NOW - timedelta(minutes=3),
            created_at=NOW - timedelta(minutes=3),
        )
    )
    session.add(
        MerchantOrder(
            paypal_order_id="PAYPAL-ORDER-1",
            merchant_reference="MERCHANT-REF-1",
            amount=None,
            currency=None,
            status="CREATED",
            paypal_created_at=NOW - timedelta(minutes=3),
        )
    )
    session.commit()


def _response(
    probable_cause=None,
    evidence_ids=None,
) -> LLMInvestigationResponse:
    return LLMInvestigationResponse(
        probable_cause=probable_cause,
        probable_cause_evidence_ids=evidence_ids or [],
        confidence="LOW",
        confidence_basis="Only a small set of PayPal records is available.",
        recommended_action="Check the payment processing window before escalation.",
    )


def test_service_runs_deterministic_and_llm_steps_and_persists_history(db_session):
    _seed_case(db_session)
    provider = SequenceProvider([_response()])
    service = InvestigationService(
        settings=_settings(), provider=provider, clock=lambda: NOW
    )

    report = asyncio.run(service.run(db_session, CASE_ID))

    assert report.case_id == CASE_ID
    assert report.investigation_status == "INCONCLUSIVE"
    assert report.probable_cause is None
    assert report.requires_human_approval is True
    assert report.model_metadata["provider"] == "ollama"
    assert provider.prompts
    assert "merchant_source_orders" in provider.prompts[0]
    saved = db_session.get(InvestigationReportRecord, report.report_id)
    assert saved is not None
    assert saved.evidence_snapshot["case_id"] == CASE_ID
    assert saved.validation_errors == []


def test_service_retries_unknown_evidence_reference_once(db_session):
    _seed_case(db_session)
    provider = SequenceProvider(
        [
            _response("Unsupported explanation", ["EVD-not-in-this-snapshot"]),
            _response(),
        ]
    )
    service = InvestigationService(
        settings=_settings(), provider=provider, clock=lambda: NOW
    )

    report = asyncio.run(service.run(db_session, CASE_ID))

    assert report.investigation_status == "INCONCLUSIVE"
    assert len(provider.prompts) == 2
    assert "previous response was rejected" in provider.prompts[1]


def test_provider_failure_saves_failed_attempt_without_changing_payment_state(
    db_session,
):
    _seed_case(db_session)
    provider = SequenceProvider(
        [
            InvestigationProviderError("Provider unavailable."),
            InvestigationProviderError("Provider unavailable."),
        ]
    )
    service = InvestigationService(
        settings=_settings(), provider=provider, clock=lambda: NOW
    )

    with pytest.raises(InvestigationRunError, match="Provider unavailable"):
        asyncio.run(service.run(db_session, CASE_ID))

    saved = db_session.query(InvestigationReportRecord).one()
    assert saved.investigation_status == "FAILED"
    assert saved.probable_cause is None
    assert saved.requires_human_approval is True
    assert saved.validation_errors == ["Provider unavailable."]
    assert db_session.get(MerchantOrder, 1).status == "CREATED"


def test_service_returns_not_found_for_unpersisted_case(db_session):
    service = InvestigationService(settings=_settings(), provider=SequenceProvider([]))

    with pytest.raises(InvestigationCaseNotFound):
        asyncio.run(service.run(db_session, CASE_ID))


def test_api_validates_case_and_exposes_latest_report_and_history(
    db_session, api_client
):
    _seed_case(db_session)
    provider = SequenceProvider([_response()])
    service = InvestigationService(
        settings=_settings(), provider=provider, clock=lambda: NOW
    )
    report = asyncio.run(service.run(db_session, CASE_ID))

    latest = api_client.get(f"/api/investigations/{CASE_ID}")
    history = api_client.get(f"/api/investigations/{CASE_ID}/reports")
    specific = api_client.get(
        f"/api/investigations/reports/{report.report_id}"
    )
    unknown = api_client.get(
        "/api/investigations/recon_ffffffffffffffffffff/reports"
    )

    assert latest.status_code == 200
    assert latest.json()["report_id"] == report.report_id
    assert history.status_code == 200
    assert len(history.json()) == 1
    assert specific.status_code == 200
    assert unknown.status_code == 404


def test_api_returns_not_found_for_unknown_case_on_run_and_validate(api_client):
    unknown = "recon_ffffffffffffffffffff"

    run_response = api_client.post(f"/api/investigations/{unknown}/run")
    validate_response = api_client.post(
        f"/api/investigations/{unknown}/validate"
    )

    assert run_response.status_code == 404
    assert validate_response.status_code == 404
