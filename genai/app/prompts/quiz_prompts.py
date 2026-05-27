"""퀴즈 생성 프롬프트"""

QUIZ_SYSTEM = """당신은 금융 교육 전문 AI입니다.
사용자의 금융 지식 수준을 측정하기 위한 퀴즈 문제를 생성합니다.

## 난이도 기준 (1.0 ~ 5.0)
- 1.0~1.9: 입문 — 주식이란 무엇인가, 코스피/코스닥, 배당이란
- 2.0~2.9: 초보 — 시가총액, 주가수익비율(PER), ETF, 분산투자
- 3.0~3.9: 중급 — PBR, EPS, ROE, 기술적 분석 기초, 이동평균선
- 4.0~4.9: 고급 — 재무제표 분석, DCF 밸류에이션, 섹터 로테이션
- 5.0: 전문 — 매크로경제 지표, 파생상품(옵션/선물), 알고리즘 트레이딩

## 출력 형식 (JSON)
아래 JSON 구조로만 응답하세요. 다른 텍스트 없이 JSON만 출력합니다.

```json
{
  "question": "문제 텍스트",
  "type": "multiple_choice",
  "choices": {
    "A": "보기 A",
    "B": "보기 B",
    "C": "보기 C",
    "D": "보기 D"
  },
  "answer": "B",
  "explanation": "정답 해설 (왜 맞는지, 개념 설명 포함, 2-3문장)",
  "difficulty": 2.5
}
```

OX 문제의 경우:
```json
{
  "question": "문제 텍스트 (참/거짓으로 답하세요)",
  "type": "ox",
  "choices": {
    "O": "참 (맞다)",
    "X": "거짓 (틀리다)"
  },
  "answer": "O",
  "explanation": "해설",
  "difficulty": 1.5
}
```

## 중요 원칙
- 한국어로 출제합니다.
- 이미 출제된 주제와 겹치지 않도록 합니다.
- 모호하지 않고 명확한 정답이 있는 문제를 출제합니다.
- 난이도에 맞는 어휘와 개념을 사용합니다."""


def build_quiz_messages(difficulty: float, asked_topics: list[str]) -> list[dict]:
    """퀴즈 문제 생성 메시지"""
    topics_hint = ""
    if asked_topics:
        topics_hint = f"\n이미 출제된 주제 (중복 금지): {', '.join(asked_topics[-10:])}"

    # 난이도에 따라 문제 유형 결정 (낮은 난이도 → OX 포함, 높은 난이도 → 객관식 위주)
    if difficulty <= 2.0:
        type_hint = "객관식(multiple_choice) 또는 OX 문제 중 랜덤으로 출제하세요."
    else:
        type_hint = "객관식(multiple_choice) 문제를 출제하세요."

    content = (
        f"현재 난이도: {difficulty:.1f}\n"
        f"{topics_hint}\n\n"
        f"위 난이도에 맞는 금융 지식 퀴즈 문제 1개를 생성하세요.\n"
        f"{type_hint}"
    )
    return [{"role": "user", "content": content}]


def build_level_summary_messages(questions_answered: int,
                                 correct_count: int,
                                 final_level: int,
                                 difficulty_history: list[float]) -> list[dict]:
    """레벨 테스트 결과 메시지 생성"""
    accuracy = correct_count / questions_answered * 100 if questions_answered > 0 else 0
    content = (
        f"퀴즈 결과:\n"
        f"- 총 {questions_answered}문제 중 {correct_count}문제 정답\n"
        f"- 정답률: {accuracy:.0f}%\n"
        f"- 최종 레벨: {final_level}단계\n\n"
        f"사용자에게 레벨 결과를 친근하게 설명해주세요. (2-3문장, 한국어)"
    )
    return [{"role": "user", "content": content}]
