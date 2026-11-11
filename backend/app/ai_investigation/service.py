from __future__ import annotations

from datetime import datetime, timedelta, timezone
from collections.abc import Callable
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_investigation.evidence_collector import collect_investigation_evidence
from app.ai_investigation.prompts import PROMPT_VERSION, build_investigation_prompt
from app.ai_investigation.provider import (
    InvestigationProviderError,
    InvestigationLLMProvider,
    OllamaInvestigationProvider,
)
from app.ai_investigation.root_cause_engine import analyze_case
from app.ai_investigation.schemas import (
    DeterministicAnalysis,
    InvestigationEvidenceSnapshot,
    InvestigationFinding,
    InvestigationReport,
    InvestigationValidationResult,
    LLMInvestigationResponse,
)
from app.ai_investigation.timeline_builder import build_payment_timeline
from app.ai_investigation.validator import (
    ReportValidationError,
    validate_llm_response,
    validate_report,
)
from app.core.config import Settings, get_settings
from app.models import (
    InvestigationReportRecord,
    ReconciliationExceptionRecord,
)
from app.utils.timestamps import utcnow


class InvestigationCaseNotFound(LookupError):
    pass


class InvestigationRunError(RuntimeError):
    def __init__(self, message: str, *, provider_failure: bool) -> None:
        super().__init__(message)
        self.provider_failure = provider_failure


class InvestigationService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        provider: InvestigationLLMProvider | None = None,
        clock: Callable[[], datetime] = utcnow,
        max_attempts: int = 2,
    ) -> None:
        if max_attempts < 1 or max_attempts > 2:
            raise ValueError("Investigation model retries must be between 1 and 2.")
        self._settings = settings or get_settings()
        self._provider = provider or OllamaInvestigationProvider(self._settings)
        self._clock = clock
        self._max_attempts = max_attempts

    def validate(self, session: Session, case_id: str) -> InvestigationValidationResult:
        case = self._get_case(session, case_id)
        snapshot, analysis = self._collect_and_analyze(session, case)
        return InvestigationValidationResult(
            case_id=case.case_id,
            evidence_count=len(snapshot.evidence),
            timeline_count=len(snapshot.timeline),
            finding_count=len(analysis.findings),
            payment_state=analysis.payment_state,
            missing_evidence=analysis.missing_evidence,
            conflicting_evidence=analysis.conflicting_evidence,
            source_availability=snapshot.source_availability,
            validated_at=self._clock(),
        )

    async def run(self, session: Session, case_id: str) -> InvestigationReport:
        case = self._get_case(session, case_id)
        snapshot, analysis = self._collect_and_analyze(session, case)
        metadata = {
            "case_id": case.case_id,
            "issue_type": case.exception_type,
            "severity": case.severity,
            "case_status": case.case_status,
        }
        prompt = build_investigation_prompt(
            case_metadata=metadata,
            deterministic_analysis=analysis.model_dump(mode="json"),
            evidence_snapshot=snapshot.model_dump(mode="json"),
        )
        response: LLMInvestigationResponse | None = None
        error: Exception | None = None
        for attempt in range(self._max_attempts):
            try:
                response = await self._provider.generate(prompt)
                validate_llm_response(response, snapshot.evidence)
                break
            except (InvestigationProviderError, ReportValidationError) as caught:
                error = caught
                response = None
                if attempt + 1 < self._max_attempts:
                    prompt += (
                        "\nThe previous response was rejected. Correct this issue "
                        "without adding any evidence or unsupported claims: "
                        + str(caught)
                    )

        if response is None:
            error_message = (
                str(error)
                if isinstance(error, InvestigationProviderError)
                else "Provider output failed investigation evidence validation."
            )
            failed = self._failed_report(case, analysis)
            session.add(
                _record_from_report(
                    failed,
                    snapshot,
                    analysis,
                    validation_errors=[error_message],
                )
            )
            session.commit()
            raise InvestigationRunError(
                error_message,
                provider_failure=isinstance(error, InvestigationProviderError),
            )

        findings = list(analysis.findings)
        if response.probable_cause is not None:
            findings.append(
                InvestigationFinding(
                    finding_id="HYPOTHESIS-CAUSE",
                    claim="Possible explanation: " + response.probable_cause,
                    finding_type="HYPOTHESIS",
                    evidence_ids=response.probable_cause_evidence_ids,
                    explanation=(
                        "This is a qualitative LLM-generated hypothesis, not a "
                        "verified fact or calibrated probability."
                    ),
                )
            )
        report = InvestigationReport(
            report_id=str(uuid4()),
            case_id=case.case_id,
            issue_type=case.exception_type,
            severity=case.severity,
            investigation_status=(
                "COMPLETED"
                if response.probable_cause is not None
                else "INCONCLUSIVE"
            ),
            probable_cause=response.probable_cause,
            findings=findings,
            missing_evidence=analysis.missing_evidence,
            conflicting_evidence=analysis.conflicting_evidence,
            confidence=response.confidence,
            confidence_basis=(
                response.confidence_basis
                + " Confidence is qualitative and not calibrated."
            ),
            recommended_action=response.recommended_action,
            requires_human_approval=True,
            investigated_at=self._clock(),
            model_metadata={
                "provider": self._settings.investigation_llm_provider,
                "model": self._settings.ollama_model,
                "prompt_version": PROMPT_VERSION,
            },
        )
        report = validate_report(
            report,
            requested_case_id=case_id,
            issue_type=case.exception_type,
            severity=case.severity,
            evidence=snapshot.evidence,
        )
        session.add(_record_from_report(report, snapshot, analysis))
        session.commit()
        return report

    def _get_case(
        self, session: Session, case_id: str
    ) -> ReconciliationExceptionRecord:
        case = session.scalar(
            select(ReconciliationExceptionRecord).where(
                ReconciliationExceptionRecord.case_id == case_id
            )
        )
        if case is None:
            raise InvestigationCaseNotFound("Reconciliation exception case not found.")
        return case

    def _collect_and_analyze(
        self, session: Session, case: ReconciliationExceptionRecord
    ) -> tuple[InvestigationEvidenceSnapshot, DeterministicAnalysis]:
        snapshot = collect_investigation_evidence(session, case)
        snapshot = snapshot.model_copy(
            update={"timeline": build_payment_timeline(snapshot.evidence)}
        )
        now = self._clock()
        analysis = analyze_case(
            case,
            snapshot,
            now=now,
            missing_payment_threshold=timedelta(
                minutes=self._settings.investigation_missing_payment_minutes
            ),
            webhook_delay_threshold=timedelta(
                minutes=self._settings.investigation_webhook_delay_minutes
            ),
            merchant_update_threshold=timedelta(
                minutes=self._settings.investigation_merchant_update_minutes
            ),
            capture_confirmation_threshold=timedelta(
                minutes=self._settings.investigation_capture_confirmation_minutes
            ),
            accounting_delay_threshold=timedelta(
                minutes=self._settings.investigation_accounting_delay_minutes
            ),
        )
        return snapshot, analysis

    def _failed_report(
        self,
        case: ReconciliationExceptionRecord,
        analysis: DeterministicAnalysis,
    ) -> InvestigationReport:
        return InvestigationReport(
            report_id=str(uuid4()),
            case_id=case.case_id,
            issue_type=case.exception_type,
            severity=case.severity,
            investigation_status="FAILED",
            findings=analysis.findings,
            missing_evidence=analysis.missing_evidence,
            conflicting_evidence=analysis.conflicting_evidence,
            confidence="LOW",
            confidence_basis=(
                "No valid LLM response passed validation; no probable cause "
                "was generated."
            ),
            recommended_action=(
                "Retry the investigation after verifying provider availability."
            ),
            requires_human_approval=True,
            investigated_at=self._clock(),
            model_metadata={
                "provider": self._settings.investigation_llm_provider,
                "model": self._settings.ollama_model,
                "prompt_version": PROMPT_VERSION,
            },
        )

def _record_from_report(
    report: InvestigationReport,
    snapshot: InvestigationEvidenceSnapshot,
    analysis: DeterministicAnalysis,
    *,
    validation_errors: list[str] | None = None,
) -> InvestigationReportRecord:
    model_metadata = report.model_metadata
    return InvestigationReportRecord(
        report_id=report.report_id,
        case_id=report.case_id,
        investigation_status=report.investigation_status,
        issue_type=report.issue_type,
        severity=report.severity,
        probable_cause=report.probable_cause,
        findings=[item.model_dump(mode="json") for item in report.findings],
        missing_evidence=report.missing_evidence,
        conflicting_evidence=report.conflicting_evidence,
        evidence_snapshot=snapshot.model_dump(mode="json"),
        deterministic_analysis=analysis.model_dump(mode="json"),
        confidence=report.confidence,
        confidence_basis=report.confidence_basis,
        recommended_action=report.recommended_action,
        requires_human_approval=True,
        llm_provider=model_metadata.get("provider"),
        llm_model=model_metadata.get("model"),
        prompt_version=model_metadata.get("prompt_version", PROMPT_VERSION),
        validation_errors=validation_errors or [],
        investigated_at=report.investigated_at,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def report_from_record(record: InvestigationReportRecord) -> InvestigationReport:
    return InvestigationReport(
        report_id=record.report_id,
        case_id=record.case_id,
        issue_type=record.issue_type,
        severity=record.severity,
        investigation_status=record.investigation_status,
        probable_cause=record.probable_cause,
        findings=record.findings,
        missing_evidence=record.missing_evidence,
        conflicting_evidence=record.conflicting_evidence,
        confidence=record.confidence or "LOW",
        confidence_basis=record.confidence_basis or "Confidence basis unavailable.",
        recommended_action=record.recommended_action
        or "Review evidence manually.",
        requires_human_approval=True,
        investigated_at=record.investigated_at,
        model_metadata={
            key: value
            for key, value in {
                "provider": record.llm_provider,
                "model": record.llm_model,
                "prompt_version": record.prompt_version,
            }.items()
            if value is not None
        },
    )
