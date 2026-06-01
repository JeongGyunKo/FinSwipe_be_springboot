package com.finswipe.controller;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestClient;

import java.nio.charset.StandardCharsets;

@Tag(name = "Quiz", description = "금융 지식 퀴즈 — 레벨 측정(7문제) + 투자 성향 분석(3문제)")
@SecurityRequirement(name = "bearerAuth")
@RestController
@RequestMapping("/quiz")
@Slf4j
public class QuizController {

    private final RestClient genaiClient;

    public QuizController(@Qualifier("genaiRestClient") RestClient genaiClient) {
        this.genaiClient = genaiClient;
    }

    @Operation(summary = "퀴즈 세션 생성", description = "새 퀴즈 시작. body에 user_id(UUID) 선택 전달.")
    @PostMapping("/sessions")
    public ResponseEntity<String> createSession(
            @RequestBody(required = false) String body) {
        return proxyPost("/api/v1/quiz/sessions", body != null ? body : "{}");
    }

    @Operation(summary = "세션 상태 조회", description = "현재 진행 상황 (questions_asked, status, final_level 등)")
    @GetMapping("/sessions/{sessionId}")
    public ResponseEntity<String> getSession(@PathVariable String sessionId) {
        return proxyGet("/api/v1/quiz/sessions/" + sessionId);
    }

    @Operation(summary = "다음 문제 요청", description = "Q1~7: Gemini가 금융 지식 문제 생성 / Q8~10: 고정 성향 질문. 응답에 question_type 포함.")
    @PostMapping("/sessions/{sessionId}/next-question")
    public ResponseEntity<String> nextQuestion(@PathVariable String sessionId) {
        return proxyPost("/api/v1/quiz/sessions/" + sessionId + "/next-question", null);
    }

    @Operation(summary = "답변 제출", description = "answer: A~E (E=잘 모르겠다). 10문제 완료 시 final_level + tendency 반환.")
    @PostMapping("/sessions/{sessionId}/answers")
    public ResponseEntity<String> submitAnswer(
            @PathVariable String sessionId,
            @RequestBody String body) {
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
}
