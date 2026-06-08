from __future__ import annotations

import logging
from app.core import get_settings
from app.db.postgres import connect_postgres
from app.services.gemini.client import gemini_generate_content

logger = logging.getLogger(__name__)

_AREAS_KO = ["기본개념", "마켓수급", "매크로", "펀더멘털", "리스크관리"]

_SYSTEM_PROMPT = """당신은 개인 투자 학습 코치입니다.
사용자의 퀴즈 영역별 점수를 분석하여 강점과 약점을 파악하고,
구체적인 학습 방향을 제시해주세요. 반드시 한국어로, 친근하고 격려하는 톤으로 답변하세요.
"""


def coach(user_id: str) -> dict:
    settings = get_settings()

    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            # 최근 퀴즈 세션의 area_stats 조회
            cur.execute(
                """
                SELECT area_stats, correct_count, questions_asked, analysis_depth
                FROM quiz_sessions
                WHERE user_id = %s AND status = 'completed' AND area_stats IS NOT NULL
                ORDER BY created_at DESC LIMIT 3
                """,
                (user_id,),
            )
            sessions = cur.fetchall()

    if not sessions:
        return {"coaching": None, "message": "완료된 퀴즈 기록이 없습니다. 먼저 퀴즈를 풀어보세요!"}

    # 가장 최근 세션 기준
    latest = sessions[0]
    area_stats = latest["area_stats"] or {}

    # area_stats에서 대표 성향 도출 (tendency 컬럼은 quiz_sessions에 없음)
    tested = {a: (area_stats.get(a) or {}).get("score") for a in _AREAS_KO if (area_stats.get(a) or {}).get("score") is not None}
    strongest_area = max(tested, key=lambda k: tested[k]) if tested else "기본개념"
    _TENDENCY_LABEL = {
        "기본개념": "탐색형 투자자", "마켓수급": "모멘텀형 투자자",
        "매크로": "거시경제형 투자자", "펀더멘털": "가치투자형 투자자",
        "리스크관리": "안정추구형 투자자",
    }
    tendency_label = _TENDENCY_LABEL.get(strongest_area, "탐색형 투자자")

    # 영역별 점수 정리
    area_summary = []
    for area in _AREAS_KO:
        stat = area_stats.get(area, {})
        score = stat.get("score") or 0.0  # score가 None이면 0.0으로 처리
        correct = stat.get("correct", 0)
        total = stat.get("total", 0)
        area_summary.append(f"- {area}: {score:.1f}점 ({correct}/{total}문제 정답)")

    # 복수 세션이면 추세도 계산
    trend_text = ""
    if len(sessions) >= 2:
        prev = sessions[1]["area_stats"] or {}
        improvements = []
        for area in _AREAS_KO:
            curr_score = (area_stats.get(area) or {}).get("score") or 0.0
            prev_score = (prev.get(area) or {}).get("score") or 0.0
            if curr_score > prev_score:
                improvements.append(f"{area}(+{curr_score - prev_score:.1f}점)")
        if improvements:
            trend_text = f"\n전 회차 대비 향상된 영역: {', '.join(improvements)}"

    user_prompt = f"""
사용자 퀴즈 결과:
정답률: {latest['correct_count']}/{latest['questions_asked']}문제
투자 성향: {tendency_label}
분석 깊이: {latest.get('analysis_depth') or 'basic'}

영역별 점수:
{chr(10).join(area_summary)}
{trend_text}

이 사용자에게 맞는 학습 코칭을 다음 형식으로 제공해주세요:
1. 강점 영역 칭찬 (1~2문장)
2. 집중 보완이 필요한 영역과 구체적 학습 방법 (2~3문장)
3. 다음 목표 제안 (1문장)
"""

    try:
        coaching = gemini_generate_content(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model=settings.gemini_summary_model,
            temperature=0.4,
            request_label="learning_coach",
        )

        weak_areas = sorted(
            [(area, (area_stats.get(area) or {}).get("score", 0)) for area in _AREAS_KO],
            key=lambda x: x[1]
        )[:2]

        return {
            "coaching": coaching.strip(),
            "area_stats": area_stats,
            "weak_areas": [a[0] for a in weak_areas],
            "tendency": tendency_label,
            "sessions_analyzed": len(sessions),
        }

    except Exception as e:
        logger.error("[코치] 실패: %s", e, exc_info=True)
        return {"coaching": None, "error": "코칭 분석 중 오류가 발생했습니다."}
