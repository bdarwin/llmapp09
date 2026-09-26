from collections.abc import Callable
from typing import TypeVar

from fastapi import APIRouter, HTTPException
from langfuse import get_client, observe, propagate_attributes

from app.config import settings
from app.dto.classification_response import ClassificationResponse
from app.dto.intent_response import IntentResponse
from app.dto.sentiment_response import SentimentResponse
from app.dto.summary_response import SummaryResponse
from app.dto.text_request import TextRequest
from app.guardrails import GuardrailBlockedError, guardrails_engine
from app.monitoring import metrics_store
from app.router.model_router import model_router
from app.service.ai_service import AIService

router = APIRouter(prefix="/api/ai", tags=["AI Text Analysis"])

ai_service = AIService()
# app.config (imported above) loads the .env file first, so the client picks up
# the LANGFUSE_* credentials
langfuse = get_client()

T = TypeVar("T")


@observe(as_type="guardrail", name="guard-input", capture_input=False, capture_output=False)
def _guarded_input(text: str, task_type: str) -> str:
    """Runs the input guardrails and returns the (possibly redacted) text to
    send to the model, or raises HTTPException if a detection blocks it."""
    try:
        sanitized = guardrails_engine.check_input(text, task_type)
    except GuardrailBlockedError as e:
        langfuse.update_current_span(
            level="WARNING",
            status_message=f"blocked [{e.category}]: {e.details}",
            metadata={"blocked": True, "category": e.category},
        )
        langfuse.score_current_trace(
            name="guardrail-blocked",
            value=True,
            data_type="BOOLEAN",
            comment=f"{e.category}: {e.details}",
        )
        raise HTTPException(
            status_code=400,
            detail=f"Request blocked by guardrail [{e.category}]: {e.details}",
        )

    # Only the sanitized text is traced: raw secrets/PII stay out of Langfuse.
    redacted = sanitized != text
    langfuse.update_current_span(
        output=sanitized,
        metadata={"blocked": False, "redacted": redacted},
    )
    langfuse.score_current_trace(name="guardrail-blocked", value=False, data_type="BOOLEAN")
    langfuse.score_current_trace(name="input-redacted", value=redacted, data_type="BOOLEAN")
    return sanitized


def _run_task(task_type: str, text: str, analyze: Callable[[str], T]) -> T:
    """Run one analysis task as a single Langfuse trace.

    Trace input/output are set explicitly — the guarded (redacted) text and the
    validated result — so the tracing table stays readable and raw secrets/PII
    are never sent to Langfuse.
    """
    with propagate_attributes(
        trace_name=f"{task_type}-text",
        tags=[f"task:{task_type}", "api"],
        version=settings.APP_VERSION,
        environment=settings.LANGFUSE_ENVIRONMENT,
    ):
        langfuse.update_current_span(
            metadata={"task_type": task_type, "endpoint": f"/api/ai/{task_type}"},
        )
        guarded = _guarded_input(text, task_type)
        langfuse.update_current_span(input=guarded)
        result = analyze(guarded)
        langfuse.update_current_span(output=result.model_dump())
        return result


@router.post(
    "/classify",
    response_model=ClassificationResponse,
    summary="Classify Text",
    description="Analyzes text and returns classification labels, tags, and primary category",
)
@observe(name="classify-text", capture_input=False, capture_output=False)
def classify_text(request: TextRequest) -> ClassificationResponse:
    return _run_task("classify", request.text, ai_service.classify_text)


@router.post(
    "/sentiment",
    response_model=SentimentResponse,
    summary="Analyze Sentiment",
    description="Analyzes text sentiment (positive, negative, neutral) and detects specific emotions",
)
@observe(name="sentiment-text", capture_input=False, capture_output=False)
def analyze_sentiment(request: TextRequest) -> SentimentResponse:
    return _run_task("sentiment", request.text, ai_service.analyze_sentiment)


@router.post(
    "/summarize",
    response_model=SummaryResponse,
    summary="Summarize Text",
    description="Generates a concise summary with key points from the provided text",
)
@observe(name="summarize-text", capture_input=False, capture_output=False)
def summarize_text(request: TextRequest) -> SummaryResponse:
    return _run_task("summarize", request.text, ai_service.summarize_text)


@router.post(
    "/intent",
    response_model=IntentResponse,
    summary="Detect Intent",
    description="Identifies the intent and purpose behind the text (question, request, statement, command)",
)
@observe(name="intent-text", capture_input=False, capture_output=False)
def detect_intent(request: TextRequest) -> IntentResponse:
    return _run_task("intent", request.text, ai_service.detect_intent)


@router.get(
    "/routes",
    summary="Get Route Configuration",
    description="Returns the current model routing table showing which model handles each task type",
)
def get_routes() -> dict[str, str]:
    return model_router.get_routes()


@router.get(
    "/guardrails",
    summary="Get Guardrails Configuration",
    description="Returns the active input/output guardrails and which detections block requests",
)
def get_guardrails_config() -> dict:
    return {
        "input_guards": {
            "prompt_injection_detector": {
                "action": "block" if settings.GUARDRAILS_BLOCK_PROMPT_INJECTION else "log_only",
            },
            "harmful_content_detector": {
                "action": "block" if settings.GUARDRAILS_BLOCK_HARMFUL_CONTENT else "log_only",
            },
            "secrets_present_detector": {
                "action": "block" if settings.GUARDRAILS_BLOCK_SECRETS else "redact",
            },
            "pii_detector": {"action": "redact"},
        },
        "output_guards": {
            "schema_validation": "Guard.for_pydantic per response DTO (type/range/enum checks)",
        },
    }


# ── Metrics endpoints ─────────────────────────────────────────────


@router.get(
    "/metrics/cost",
    summary="Get Cost Metrics",
    description="Returns token usage records and summary totals",
)
def get_cost_metrics() -> dict:
    return metrics_store.get_cost_metrics()


@router.get(
    "/metrics/performance",
    summary="Get Performance Metrics",
    description="Returns latency records with p50/p95/avg statistics",
)
def get_performance_metrics() -> dict:
    return metrics_store.get_performance_metrics()


@router.get(
    "/metrics/safety",
    summary="Get Safety Metrics",
    description="Returns prompt injection and policy violation records",
)
def get_safety_metrics() -> dict:
    return metrics_store.get_safety_metrics()
