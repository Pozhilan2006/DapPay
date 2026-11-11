from __future__ import annotations

from app.ai_investigation.schemas import (
    EvidenceItem,
    InvestigationReport,
    LLMInvestigationResponse,
)


class ReportValidationError(ValueError):
    pass


def validate_llm_response(
    response: LLMInvestigationResponse,
    evidence: list[EvidenceItem],
) -> None:
    allowed_ids = {item.evidence_id for item in evidence}
    unknown = sorted(set(response.probable_cause_evidence_ids) - allowed_ids)
    if unknown:
        raise ReportValidationError(
            "LLM response references evidence outside this investigation snapshot."
        )
    if response.probable_cause and not response.probable_cause_evidence_ids:
        raise ReportValidationError(
            "A probable-cause hypothesis must cite at least one evidence item."
        )


def validate_report(
    report: InvestigationReport,
    *,
    requested_case_id: str,
    issue_type: str,
    severity: str,
    evidence: list[EvidenceItem],
) -> InvestigationReport:
    if report.case_id != requested_case_id:
        raise ReportValidationError(
            "Investigation report case ID does not match the requested case."
        )
    if report.issue_type != issue_type or report.severity != severity:
        raise ReportValidationError(
            "Investigation report changed the authoritative case classification."
        )
    evidence_ids = {item.evidence_id for item in evidence}
    for finding in report.findings:
        unknown = set(finding.evidence_ids) - evidence_ids
        if unknown:
            raise ReportValidationError(
                "Investigation finding references evidence outside this snapshot."
            )
        if (
            finding.finding_type in {"FACT", "DETERMINISTIC_CONCLUSION"}
            and not finding.evidence_ids
        ):
            raise ReportValidationError(
                "Factual findings must cite at least one evidence item."
            )
    unknown_conflicts = set(report.conflicting_evidence) - evidence_ids
    if unknown_conflicts:
        raise ReportValidationError(
            "Conflicting-evidence list references unknown evidence."
        )
    if (
        report.investigation_status == "COMPLETED"
        and not any(
            finding.finding_type == "HYPOTHESIS" for finding in report.findings
        )
    ):
        raise ReportValidationError(
            "An investigation without a supported cause must be INCONCLUSIVE."
        )
    return report
