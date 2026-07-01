# 좋아요(관심있음) 기능 — FE 핸드오프

> 카드 **오른쪽 스와이프 = 관심있음**이 지금은 **아무것도 저장하지 않습니다**(`CardDeck.tsx`의 `dismiss()`가 애니메이션만 함).
> 그래서 챗봇에 "내가 좋아요한 뉴스 뭐야"를 물어도 보여줄 데이터가 없어 엉뚱한 답이 나갔습니다.
> BE에 좋아요 저장·조회·챗봇 응답을 모두 만들어 배포 준비 완료. **FE는 스와이프 시 저장 API만 호출하면 됩니다.**

---

## 0. TL;DR (FE가 할 일)
1. **오른쪽 스와이프 시 `POST /news/{id}/like` 호출** — 이것만 하면 챗봇 "좋아요한 뉴스" 답변이 바로 동작.
2. **왼쪽 스와이프 시 `POST /news/{id}/dislike` 호출** — 싫어요 저장. 싫어요한 기사는 카드 피드에 **다시 뜨지 않음**.
3. (선택) 좋아요/싫어요 취소 → `DELETE /news/{id}/like`, `DELETE /news/{id}/dislike`.
4. (선택) 목록 화면 → `GET /news/liked`, `GET /news/disliked`.

> **좋아요/싫어요는 상호배타** — 좋아요를 누르면 같은 기사의 싫어요가 자동 해제되고, 그 반대도 마찬가지. (한 기사는 좋아요 or 싫어요 중 하나만)

모든 엔드포인트 **JWT 필수**.

---

## 1. API

### A. 좋아요 / 싫어요 저장·취소
```
POST   /news/{articleId}/like      (JWT)  → 200 { "ok": true }   // 오른쪽 스와이프. 멱등
DELETE /news/{articleId}/like      (JWT)  → 200 { "ok": true }   // 좋아요 취소. 멱등
POST   /news/{articleId}/dislike   (JWT)  → 200 { "ok": true }   // 왼쪽 스와이프. 멱등
DELETE /news/{articleId}/dislike   (JWT)  → 200 { "ok": true }   // 싫어요 취소. 멱등
```
- `articleId` = 카드의 기사 UUID (피드 응답의 `id`).
- 오른쪽 스와이프(관심있음) → `POST /like`, 왼쪽 스와이프(관심없음) → `POST /dislike`.
- **상호배타**: `POST /like`는 같은 기사의 싫어요를 자동 제거, `POST /dislike`는 좋아요를 자동 제거.
- **싫어요한 기사는 카드 피드(`/news/latest` 등)에 다시 노출되지 않음** (BE에서 제외).

### B. 좋아요 / 싫어요 목록 (선택 — 별도 화면용)
```
GET /news/liked?limit=20&offset=0     (JWT)  → 200 { count, offset, data: NewsArticle[] }
GET /news/disliked?limit=20&offset=0  (JWT)  → 200 { count, offset, data: NewsArticle[] }
```
- 최신순. `data` 항목은 기존 뉴스 카드(`NewsArticle`)와 동일 구조(지표·가격·sparkline 포함).

### C. 챗봇 (BE 자동 처리 — FE 작업 없음)
- 위 `POST /like`로 좋아요가 쌓이면, 챗봇에 **"내가 좋아요한 뉴스 뭐야 / 좋아요한 기사 보여줘 / 찜한 뉴스"** 류 질문 시
  BE가 좋아요 목록을 직접 응답합니다(LLM 토큰 0). 좋아요가 없으면 "오른쪽으로 스와이프하면 저장돼요" 안내.

---

## 2. FE 변경 지점

`src/components/briefing/CardDeck.tsx` — 현재 `dismiss(dir)`는 인덱스만 넘김. 우측 스와이프에 저장 호출 추가:

```ts
const dismiss = async (dir: 1 | -1) => {
  if (gone) return;
  setGoneDir(dir);
  setGone(true);
  // 오른쪽(관심있음) → 좋아요, 왼쪽(관심없음) → 싫어요
  if (currentArticle?.id) {
    const action = dir === 1 ? 'like' : 'dislike';
    fetch(`${import.meta.env.VITE_API_BASE_URL}/news/${currentArticle.id}/${action}`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    }).catch(() => {});   // 실패해도 UX 막지 않음(낙관적)
  }
  setTimeout(() => setCurrentIndex(prev => prev + 1), 380);
};
```
- 낙관적 처리 권장(실패 무시) — 스와이프 흐름을 막지 않기.
- 좋아요/싫어요는 상호배타이므로 취소 API는 명시적 "취소" 버튼이 있을 때만 쓰면 됨.

---

## 3. 참고 / 주의
- **과거 스와이프는 복구 불가** — 지금까지 우측 스와이프는 저장된 적이 없습니다. FE 연동 이후의 좋아요만 쌓입니다.
- "관심 종목(워치리스트)" 화면(`/like`)과는 **별개**입니다. 그건 종목 단위 관심, 이건 기사 단위 좋아요.
- BE 저장 위치: 좋아요 `user_liked_articles`(Flyway V37, `user_id, article_id, liked_at`), 싫어요 `user_disliked_articles`(Flyway V36, `user_id, article_id, disliked_at`).

문의: BE 관련 막히면 Swagger의 `POST /news/{articleId}/like` 참고.
