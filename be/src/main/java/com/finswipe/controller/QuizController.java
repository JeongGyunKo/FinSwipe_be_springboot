package com.finswipe.controller;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.ExampleObject;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestClient;

import java.nio.charset.StandardCharsets;

@Tag(name = "Quiz", description = "금융 지식 퀴즈 — 10문제(5영역×2)로 레벨·투자성향 측정. 온보딩용으로 비로그인 허용(POST는 퀴즈 전용 레이트리밋 적용).")
@RestController
@RequestMapping("/quiz")
@Slf4j
public class QuizController {

    private final RestClient genaiClient;

    public QuizController(@Qualifier("genaiRestClient") RestClient genaiClient) {
        this.genaiClient = genaiClient;
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
