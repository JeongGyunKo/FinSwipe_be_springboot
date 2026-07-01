# 카드 피드 삽입형 퀴즈 — FE 핸드오프

카드 피드를 넘기다 보면 중간중간 퀴즈 문제 카드가 하나씩 나오는 기능. **하루 2문제**, **랜덤 위치**, **로그인 유저 전용**, **레벨 맞춤(적응형)**.

온보딩 진단 퀴즈(`/quiz/sessions/**`, 10문제 세션)와는 **완전히 별개**입니다. 아래 두 엔드포인트만 쓰면 됩니다.

---

## 동작 요약

- 유저마다 `feed_quiz_difficulty`(1.0~5.0 실수)를 서버가 관리. **처음엔 3.0(중간)에서 시작.**
- 답을 맞추면 +0.34, 틀리면 -0.5 → 반올림한 정수가 그날 출제 레벨.
  - 하루 2문제 다 틀리면 딱 한 레벨 내려감. 올라가려면 3번 맞춰야 함(내려가긴 쉽고 올라가긴 신중).
- **이미 푼 문제는 다시 안 나옴.** 풀이 마르면 인접 레벨 → 가장 오래전 푼 문제 순으로 재활용(절대 빈손 안 됨).
- 서버는 문제를 낼 때 자동으로 "본 문제"로 기록. FE가 따로 seen 처리할 필요 없음.

---

## 삽입 규칙 (FE 담당)

"하루 2문제 / 랜덤 위치" 판단은 **전적으로 FE**가 합니다. 서버는 요청하면 그냥 문제를 하나 줄 뿐.

권장 로직:

```js
// localStorage: { date: "2026-07-01", shown: 0 }
const KEY = "finswipe.feedQuiz";

function todayState() {
  const today = new Date().toISOString().slice(0, 10);
  let s = JSON.parse(localStorage.getItem(KEY) || "{}");
  if (s.date !== today) s = { date: today, shown: 0 }; // 날짜 바뀌면 리셋
  return s;
}

// 카드 덱을 만들 때: 오늘 2문제 미만이면 랜덤 위치에 퀴즈 슬롯 하나 꽂기
function maybeInsertQuizSlot(cards) {
  const s = todayState();
  if (s.shown >= 2) return cards;                  // 오늘 할당량 소진
  if (cards.length < 4) return cards;              // 카드 너무 적으면 스킵
  const pos = 3 + Math.floor(Math.random() * Math.min(cards.length - 3, 5)); // 3~7번째 사이
  const deck = [...cards];
  deck.splice(pos, 0, { type: "quiz-slot" });      // 퀴즈 자리표시
  return deck;
}
```

- `quiz-slot` 카드가 화면에 도달하면 그때 `GET /quiz/single` 호출(선요청도 가능).
- 문제를 실제로 노출했으면 `s.shown += 1` 후 저장.
- 하루 1회만 삽입 시도하고 싶으면 세션당 1회 `maybeInsertQuizSlot`만 호출하는 식으로 조절.
- 로그인 안 한 유저에게는 슬롯을 아예 꽂지 마세요(엔드포인트가 401 반환).

---

## API

### 1) 문제 받기

```
GET /quiz/single
Authorization: Bearer <JWT>
```

**200 OK**
```json
{
  "question_id": "uuid",
  "level": 3,
  "area": "펀더멘털",
  "question_text": "PER(주가수익비율)이 낮다는 것은 일반적으로 무엇을 의미하나요?",
  "choices": { "A": "주가가 이익 대비 저평가", "B": "배당이 높음", "C": "거래량이 많음", "D": "부채가 적음" },
  "user_level": 3
}
```
- `choices` 키(A/B/C/D)는 문제마다 개수가 다를 수 있음. 객체 순회로 렌더.
- `correct_answer`·`explanation`은 **여기서 안 줌**(정답 노출 방지). 제출 응답에서 받음.

**204 No Content** — 출제 가능한 문제가 없음(문제 풀이 비어있을 때). 이 경우 퀴즈 카드를 건너뛰세요.
**401** — 비로그인.

### 2) 답 제출

```
POST /quiz/single/check
Authorization: Bearer <JWT>
Content-Type: application/json

{ "question_id": "uuid", "answer": "A" }
```

**200 OK**
```json
{
  "is_correct": false,
  "correct_answer": "A",
  "explanation": "PER이 낮으면 이익 대비 주가가 저평가된 신호로 해석됩니다.",
  "difficulty": 2.5,
  "level": 3
}
```
- `answer`는 선택지 키("A"~). 대소문자 무시.
- 제출하면 서버가 레벨을 갱신함. `difficulty`(실수)·`level`(반올림 정수)은 갱신 후 값.
- 제출은 선택 — 답 안 하고 넘겨도 문제는 이미 "본 문제"로 기록돼 재출제 안 됨. 단 레벨 조정은 제출해야 반영됨.

---

## 문제 풀 현황

초기 문제 **45문항**이 시드되어 있습니다(마이그레이션 V42). 레벨1~5 × 5영역, 시작점인 레벨3(중급)에 가장 두껍게 배분(5/8/15/10/7).

- 레벨별 문제 수가 적은 편(특히 레벨1·5)이라, 활발한 유저는 해당 레벨을 빠르게 소진할 수 있음 → 그때는 서버가 자동으로 인접 레벨/재활용으로 폴백하므로 노출은 계속 됩니다.
- 문항을 추가하려면 `quiz_single_questions`에 같은 형식으로 INSERT(레벨·영역·choices JSON·correct_answer·explanation)하면 즉시 반영됩니다.
