from app.ai_investigation.schemas import LLMInvestigationResponse


def response_schema() -> dict[str, object]:
    return LLMInvestigationResponse.model_json_schema()
