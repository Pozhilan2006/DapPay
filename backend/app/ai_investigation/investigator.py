from sqlalchemy.orm import Session

from app.ai_investigation.schemas import InvestigationReport
from app.ai_investigation.service import InvestigationService


async def investigate(
    *, session: Session, case_id: str
) -> InvestigationReport:
    return await InvestigationService().run(session, case_id)
