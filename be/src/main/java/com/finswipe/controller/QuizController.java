package com.finswipe.controller;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.ExampleObject;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestClient;

import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Tag(name = "Quiz", description = "금융 지식 퀴즈. ① 온보딩 세션(/quiz/sessions/**): 10문제(5영역×2)로 레벨·투자성향 측정, 비로그인 허용. "
        + "② 피드 삽입형 단일 문제(/quiz/single, /quiz/single/check): 로그인 유저의 적응형 레벨에 맞춘 무상태 1문제 — 카드 피드 사이 노출용, 중복 출제 방지. "
        + "POST는 퀴즈 전용 레이트리밋 적용.")
@RestController
@RequestMapping("/quiz")
@Slf4j
public class QuizController {

    private final RestClient genaiClient;
    private final JdbcTemplate jdbc;
    private final ObjectMapper objectMapper;

    public QuizController(@Qualifier("genaiRestClient") RestClient genaiClient,
                          JdbcTemplate jdbc,
                          ObjectMapper objectMapper) {
        this.genaiClient = genaiClient;
        this.jdbc = jdbc;
        this.objectMapper = objectMapper;
    }

    @Operation(summary = "퀴즈 세션 생성", description = "새 퀴즈 시작. body에 user_id(UUID) 선택 전달.")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            {
              "session_id": "uuid",
              "status": "in_progress",
              "current_difficulty": 1.0,
              "questions_asked": 0,
              "correct_count": 0,
              "total_questions": 10,
              "knowledge_questions": 10
            }
            """)))
    @PostMapping("/sessions")
    public ResponseEntity<String> createSession(
            @RequestBody(required = false) String body) {
        return proxyPost("/api/v1/quiz/sessions", body != null ? body : "{}");
    }

    @Operation(summary = "세션 상태 조회", description = "현재 진행 상황 (questions_asked, status, area_stats 등)")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            {
              "session_id": "uuid",
              "status": "completed",
              "questions_asked": 10,
              "correct_count": 7,
              "total_questions": 10,
              "area_stats": {
                "기본개념": { "score": 5.0, "correct": 2, "total": 2 },
                "매크로": { "score": 4.0, "correct": 2, "total": 2 },
                "펀더멘털": { "score": 2.5, "correct": 1, "total": 2 }
              }
            }
            """)))
    @GetMapping("/sessions/{sessionId}")
    public ResponseEntity<String> getSession(@PathVariable String sessionId) {
        if (!isValidUuid(sessionId)) return badSessionId();
        return proxyGet("/api/v1/quiz/sessions/" + sessionId);
    }

    @Operation(summary = "다음 문제 요청", description = "Q1~7: Gemini가 금융 지식 문제 생성. 응답에 question_type 포함.")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            {
              "question_id": "uuid",
              "question_number": 1,
              "question_type": "knowledge",
              "area": "기본개념",
              "question_text": "주식 1주를 보유하면 그 회사의 무엇이 되나요?",
              "choices": {
                "A": "채권자",
                "B": "주주 (지분 소유자)",
                "C": "임직원",
                "D": "고객",
                "E": "잘 모르겠다"
              },
              "difficulty": 1.0
            }
            """)))
    @PostMapping("/sessions/{sessionId}/next-question")
    public ResponseEntity<String> nextQuestion(@PathVariable String sessionId) {
        if (!isValidUuid(sessionId)) return badSessionId();
        return proxyPost("/api/v1/quiz/sessions/" + sessionId + "/next-question", null);
    }

    @Operation(summary = "답변 제출", description = "answer: A~E. 10문제 완료 시 area_stats(오각형 스탯) + tendency(투자 성향) 반환.")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            {
              "is_correct": true,
              "is_모름": false,
              "is_preference": false,
              "correct_answer": "B",
              "explanation": "주식 1주는 해당 기업의 아주 작은 지분(소유권)을 의미합니다.",
              "session_status": "in_progress",
              "questions_asked": 1,
              "correct_count": 1,
              "total_questions": 10,
              "knowledge_questions": 10,
              "area_stats": null,
              "tendency": null,
              "tendency_emoji": null,
              "tendency_description": null,
              "analysis_hints": null,
              "strongest_area": null
            }
            """)))
    @PostMapping("/sessions/{sessionId}/answers")
    public ResponseEntity<String> submitAnswer(
            @PathVariable String sessionId,
            @RequestBody String body) {
        if (!isValidUuid(sessionId)) return badSessionId();
        return proxyPost("/api/v1/quiz/sessions/" + sessionId + "/answers", body);
    }

    // ── 피드 삽입용 단일 문제 (무상태·로그인 전용) ────────────────────────────────

    @Operation(summary = "피드 삽입용 단일 퀴즈 문제",
            description = "로그인 유저의 현재 레벨(feed_quiz_difficulty 반올림, 미시작 시 3=중간)에 맞는 문제 1개를 반환. "
                    + "이미 푼 문제는 제외하고, 폴백 사다리는 [미출제 문제 → 레벨 근접 → 가장 오래전 푼 문제 재활용] 순. "
                    + "반환 즉시 본 문제로 기록됨. 온보딩 세션(/quiz/sessions/**)과는 무관한 독립 경로. 카드 피드 사이 인터스티셜용.")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            {
              "question_id": "uuid",
              "level": 3,
              "area": "펀더멘털",
              "question_text": "PER(주가수익비율)이 낮다는 것은 일반적으로 무엇을 의미하나요?",
              "choices": { "A": "주가가 이익 대비 저평가", "B": "배당이 높음", "C": "거래량이 많음", "D": "부채가 적음" },
              "user_level": 3
            }
            """)))
    @ApiResponse(responseCode = "204", description = "출제 가능한 문제가 없음(문제 풀 비어있음)")
    @SecurityRequirement(name = "bearerAuth")
    @GetMapping("/single")
    public ResponseEntity<?> singleQuestion(Authentication auth) {
        String uid = resolveUserId(auth);
        if (uid == null) return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                .contentType(MediaType.APPLICATION_JSON).body(Map.of("error", "로그인이 필요합니다"));

        int level = (int) Math.round(currentDifficulty(uid));

        // 폴백 사다리를 단일 쿼리로: (1)미출제 우선 → (2)레벨 근접 → (3)미출제 내 랜덤 →
        // 전부 출제됐으면 가장 오래전 푼 문제를 레벨 근접·오래된 순으로 재활용
        List<Map<String, Object>> rows = jdbc.queryForList("""
                SELECT q.id::text AS id, q.level, q.area, q.question_text, q.choices::text AS choices
                FROM quiz_single_questions q
                LEFT JOIN user_seen_quiz_questions s
                  ON s.question_id = q.id AND s.user_id = CAST(? AS UUID)
                ORDER BY (s.seen_at IS NOT NULL), ABS(q.level - ?), s.seen_at ASC NULLS FIRST, random()
                LIMIT 1
                """, uid, level);

        if (rows.isEmpty()) return ResponseEntity.noContent().build();

        Map<String, Object> row = rows.get(0);
        String qid = (String) row.get("id");

        // 본 문제 기록 — 재활용(이미 존재)이면 seen_at 갱신해 재활용 큐 맨 뒤로 보냄
        jdbc.update("""
                INSERT INTO user_seen_quiz_questions (user_id, question_id)
                VALUES (CAST(? AS UUID), CAST(? AS UUID))
                ON CONFLICT (user_id, question_id) DO UPDATE SET seen_at = NOW()
                """, uid, qid);

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("question_id", qid);
        body.put("level", row.get("level"));
        body.put("area", row.get("area"));
        body.put("question_text", row.get("question_text"));
        body.put("choices", parseJson((String) row.get("choices")));
        body.put("user_level", level);
        return ResponseEntity.ok(body);
    }

    @Operation(summary = "단일 퀴즈 답변 제출",
            description = "정답 여부·정답·해설 반환 + 유저 레벨(feed_quiz_difficulty) 갱신. "
                    + "정답 +0.34 / 오답 -0.5, 범위 1.0~5.0 clamp. 투자성향·세션과 무관.")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            {
              "is_correct": false,
              "correct_answer": "A",
              "explanation": "PER이 낮으면 이익 대비 주가가 저평가된 신호로 해석됩니다.",
              "difficulty": 2.5,
              "level": 3
            }
            """)))
    @SecurityRequirement(name = "bearerAuth")
    @PostMapping("/single/check")
    public ResponseEntity<?> checkSingle(Authentication auth, @RequestBody(required = false) SingleCheckRequest req) {
        String uid = resolveUserId(auth);
        if (uid == null) return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                .contentType(MediaType.APPLICATION_JSON).body(Map.of("error", "로그인이 필요합니다"));
        if (req == null || req.questionId() == null || req.answer() == null || !isValidUuid(req.questionId())) {
            return ResponseEntity.badRequest().contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of("error", "question_id, answer가 필요합니다"));
        }

        List<Map<String, Object>> rows = jdbc.queryForList(
                "SELECT correct_answer, explanation FROM quiz_single_questions WHERE id = CAST(? AS UUID)",
                req.questionId());
        if (rows.isEmpty()) return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .contentType(MediaType.APPLICATION_JSON).body(Map.of("error", "문제를 찾을 수 없습니다"));

        String correct = (String) rows.get(0).get("correct_answer");
        boolean isCorrect = correct != null && correct.equalsIgnoreCase(req.answer().strip());

        double delta = isCorrect ? 0.34 : -0.5;
        Double newDiff = jdbc.queryForObject("""
                UPDATE user_profiles
                SET feed_quiz_difficulty = LEAST(5.0, GREATEST(1.0, COALESCE(feed_quiz_difficulty, 3.0) + ?))
                WHERE id = CAST(? AS UUID)
                RETURNING feed_quiz_difficulty
                """, Double.class, delta, uid);

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("is_correct", isCorrect);
        body.put("correct_answer", correct);
        body.put("explanation", rows.get(0).get("explanation"));
        body.put("difficulty", newDiff);
        body.put("level", newDiff != null ? (int) Math.round(newDiff) : 3);
        return ResponseEntity.ok(body);
    }

    /** 유저의 현재 적응형 난이도 (미설정 시 3.0=중간) */
    private double currentDifficulty(String uid) {
        try {
            Double d = jdbc.queryForObject(
                    "SELECT feed_quiz_difficulty FROM user_profiles WHERE id = CAST(? AS UUID)",
                    Double.class, uid);
            return d != null ? d : 3.0;
        } catch (Exception e) {
            return 3.0;
        }
    }

    private Object parseJson(String json) {
        if (json == null || json.isBlank()) return Map.of();
        try {
            return objectMapper.readValue(json, Object.class);
        } catch (Exception e) {
            return Map.of();
        }
    }

    private static String resolveUserId(Authentication auth) {
        return (auth != null && auth.getPrincipal() instanceof java.util.UUID)
                ? auth.getPrincipal().toString() : null;
    }

    record SingleCheckRequest(
            @com.fasterxml.jackson.annotation.JsonProperty("question_id") String questionId,
            String answer) {}

    // ── 내부 ───────────────────────────────────────────────────────────────────

    private ResponseEntity<String> proxyPost(String path, String body) {
        try {
            var spec = genaiClient.post().uri(path).contentType(MediaType.APPLICATION_JSON);
            return (body != null ? spec.body(body) : spec)
                    .exchange((req, res) -> ResponseEntity
                            .status(res.getStatusCode())
                            .contentType(MediaType.APPLICATION_JSON)
                            .body(readBody(res)));
        } catch (Exception e) {
            log.error("[퀴즈 프록시] POST {} 실패: {}", path, e.getMessage());
            return genaiError();
        }
    }

    private ResponseEntity<String> proxyGet(String path) {
        try {
            return genaiClient.get().uri(path)
                    .exchange((req, res) -> ResponseEntity
                            .status(res.getStatusCode())
                            .contentType(MediaType.APPLICATION_JSON)
                            .body(readBody(res)));
        } catch (Exception e) {
            log.error("[퀴즈 프록시] GET {} 실패: {}", path, e.getMessage());
            return genaiError();
        }
    }

    private static String readBody(RestClient.RequestHeadersSpec.ConvertibleClientHttpResponse res)
            throws java.io.IOException {
        byte[] bytes = res.getBody().readAllBytes();
        return bytes.length > 0 ? new String(bytes, StandardCharsets.UTF_8) : "{}";
    }

    private static ResponseEntity<String> genaiError() {
        return ResponseEntity.internalServerError()
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"error\":\"GenAI 서버에 연결할 수 없습니다\"}");
    }

    private static boolean isValidUuid(String value) {
        try { java.util.UUID.fromString(value); return true; }
        catch (IllegalArgumentException e) { return false; }
    }

    private static ResponseEntity<String> badSessionId() {
        return ResponseEntity.badRequest()
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"error\":\"유효하지 않은 sessionId\"}");
    }
}
