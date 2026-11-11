from sqlalchemy.orm import Session

from app.ai_investigation.evidence_collector import collect_investigation_evidence
from app.ai_investigation.schemas import InvestigationEvidenceSnapshot
from app.models import ReconciliationExceptionRecord


def retrieve_evidence(
    *, session: Session, case: ReconciliationExceptionRecord
) -> InvestigationEvidenceSnapshot:
    return collect_investigation_evidence(session, case)
