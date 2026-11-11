from __future__ import annotations

from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


FindingType = Literal["FACT", "DETERMINISTIC_CONCLUSION", "HYPOTHESIS", "UNKNOWN"]
InvestigationStatus = Literal["COMPLETED", "INCONCLUSIVE", "FAILED"]
ConfidenceLevel = Literal["LOW", "MEDIUM", "HIGH"]


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InvestigationFinding(StrictSchema):
    finding_id: str = Field(min_length=1, max_length=64)
    claim: str = Field(min_length=1, max_length=2000)
    finding_type: FindingType
    evidence_ids: list[str] = Field(default_factory=list, max_length=50)
    explanation: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def facts_need_evidence(self) -> InvestigationFinding:
        if self.finding_type in {"FACT", "DETERMINISTIC_CONCLUSION"} and not self.evidence_ids:
            raise ValueError("Fact and deterministic findings must cite evidence.")
        return self


class InvestigationReport(StrictSchema):
    report_id: str = Field(min_length=1, max_length=36)
    case_id: str = Field(min_length=1, max_length=64)
    issue_type: str = Field(min_length=1, max_length=64)
    severity: str = Field(min_length=1, max_length=32)
    investigation_status: InvestigationStatus
    probable_cause: str | None = Field(default=None, max_length=4000)
    findings: list[InvestigationFinding] = Field(default_factory=list, max_length=100)
    missing_evidence: list[str] = Field(default_factory=list, max_length=100)
    conflicting_evidence: list[str] = Field(default_factory=list, max_length=100)
    confidence: ConfidenceLevel
    confidence_basis: str = Field(min_length=1, max_length=2000)
    recommended_action: str = Field(min_length=1, max_length=2000)
    requires_human_approval: Literal[True] = True
    investigated_at: AwareDatetime
    model_metadata: dict[str, str] = Field(default_factory=dict)


class EvidenceItem(StrictSchema):
    evidence_id: str
    source_system: str
    record_type: str
    source_record_id: str
    related_order_id: str | None = None
    paypal_order_id: str | None = None
    capture_id: str | None = None
    refund_id: str | None = None
    event_type: str | None = None
    occurred_at: AwareDatetime | None = None
    received_at: AwareDatetime | None = None
    processing_status: str | None = None
    verification_status: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class TimelineItem(StrictSchema):
    event_id: str
    evidence_id: str
    event_type: str
    source_system: str
    related_order_id: str | None = None
    paypal_order_id: str | None = None
    capture_id: str | None = None
    refund_id: str | None = None
    occurred_at: AwareDatetime | None = None
    received_at: AwareDatetime | None = None
    processing_status: str | None = None
    verification_status: str | None = None
    related_record_ids: list[str] = Field(default_factory=list)
    ordering_source: Literal["OCCURRED_AT", "RECEIVED_AT", "UNAVAILABLE"]


class LineageSnapshot(StrictSchema):
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    missing_relationships: list[dict[str, Any]] = Field(default_factory=list)
    disconnected_node_ids: list[str] = Field(default_factory=list)
    source_availability: dict[str, str] = Field(default_factory=dict)


class InvestigationEvidenceSnapshot(StrictSchema):
    case_id: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    timeline: list[TimelineItem] = Field(default_factory=list)
    lineage: LineageSnapshot
    missing_evidence: list[str] = Field(default_factory=list)
    source_availability: dict[str, str] = Field(default_factory=dict)


class DeterministicAnalysis(StrictSchema):
    case_id: str
    issue_type: str
    severity: str
    payment_state: Literal[
        "PENDING", "COMPLETED", "FAILED", "MISSING", "CONFLICTING", "UNKNOWN"
    ]
    financial_checks: list[dict[str, Any]] = Field(default_factory=list)
    findings: list[InvestigationFinding] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    conflicting_evidence: list[str] = Field(default_factory=list)


class LLMInvestigationResponse(StrictSchema):
    probable_cause: str | None = Field(default=None, max_length=4000)
    probable_cause_evidence_ids: list[str] = Field(default_factory=list, max_length=50)
    confidence: ConfidenceLevel
    confidence_basis: str = Field(min_length=1, max_length=2000)
    recommended_action: str = Field(min_length=1, max_length=2000)


class InvestigationValidationResult(StrictSchema):
    case_id: str
    evidence_count: int
    timeline_count: int
    finding_count: int
    payment_state: str
    missing_evidence: list[str]
    conflicting_evidence: list[str]
    source_availability: dict[str, str]
    validated_at: AwareDatetime
