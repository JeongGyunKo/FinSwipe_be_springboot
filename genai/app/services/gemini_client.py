"""Google Gemini 클라이언트 래퍼"""
import json
import logging
from typing import Any

from google import genai
from google.genai import types

from app.config import get_settings

logger = logging.getLogger(__name__)

_client: genai.Client | None = None


def get_client() -> genai.Client:
    global _client
    if _client is None:
        settings = get_settings()
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


async def call_gemini(
    system: str,
    messages: list[dict],
    *,
    use_thinking: bool = False,
    max_tokens: int = 4096,
    json_mode: bool = True,
) -> str:
    """Gemini API 비동기 호출

    Args:
        system: 시스템 프롬프트
        messages: [{role: "user"|"model", content: "..."}] 형식
        use_thinking: thinking 모드 사용 여부 (gemini-2.5-flash/pro만 지원)
        max_tokens: 최대 출력 토큰
        json_mode: JSON 응답 강제 여부
                   ※ thinking=True 시 자동으로 False — Gemini API 제약

    Returns:
        응답 텍스트
    """
    client = get_client()
    settings = get_settings()

    # contents 변환
    contents: list[types.Content] = []
    for msg in messages:
        role = msg.get("role", "user")
        if role == "assistant":
            role = "model"
        text = msg.get("content", "")
        contents.append(
            types.Content(role=role, parts=[types.Part(text=text)])
        )

    config_kwargs: dict[str, Any] = {
        "system_instruction": system,
        "max_output_tokens": max_tokens,
    }

    if use_thinking:
        # thinking 모드: response_mime_type 설정 불가 (API 제약)
        config_kwargs["thinking_config"] = types.ThinkingConfig(
            thinking_budget=-1  # -1 = 동적 사고 (모델이 자율 결정)
        )
        # json_mode는 프롬프트로 유도
    else:
        if json_mode:
            config_kwargs["response_mime_type"] = "application/json"

    config = types.GenerateContentConfig(**config_kwargs)

    try:
        response = await client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=contents,
            config=config,
        )

        if hasattr(response, "usage_metadata") and response.usage_metadata:
            um = response.usage_metadata
            logger.debug(
                "[Gemini] 토큰: in=%s out=%s",
                getattr(um, "prompt_token_count", "?"),
                getattr(um, "candidates_token_count", "?"),
            )

        return response.text or ""

    except Exception as e:
        logger.error("[Gemini] API 오류: %s: %s", type(e).__name__, e)
        raise


def extract_json(text: str) -> dict:
    """응답 텍스트에서 JSON 추출 및 파싱"""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        start = 1 if lines[0].startswith("```") else 0
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[start:end]).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        brace_start = text.find("{")
        brace_end = text.rfind("}") + 1
        if brace_start >= 0 and brace_end > brace_start:
            return json.loads(text[brace_start:brace_end])
        raise ValueError(f"JSON 파싱 실패: {text[:200]}")
