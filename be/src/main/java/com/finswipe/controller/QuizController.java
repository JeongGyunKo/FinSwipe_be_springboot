package com.finswipe.controller;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestClient;

import java.nio.charset.StandardCharsets;

@RestController
@RequestMapping("/quiz")
@Slf4j
public class QuizController {

    private final RestClient genaiClient;

    public QuizController(@Qualifier("genaiRestClient") RestClient genaiClient) {
        this.genaiClient = genaiClient;
    }

    /** POST /quiz/sessions — 퀴즈 세션 생성 */
    @PostMapping("/sessions")
    public ResponseEntity<String> createSession(
            @RequestBody(required = false) String body) {
        return proxyPost("/api/v1/quiz/sessions", body != null ? body : "{}");
    }

    /** GET /quiz/sessions/{sessionId} — 세션 상태 조회 */
    @GetMapping("/sessions/{sessionId}")
    public ResponseEntity<String> getSession(@PathVariable String sessionId) {
        return proxyGet("/api/v1/quiz/sessions/" + sessionId);
    }

    /** POST /quiz/sessions/{sessionId}/next-question — Gemini 문제 생성 */
    @PostMapping("/sessions/{sessionId}/next-question")
    public ResponseEntity<String> nextQuestion(@PathVariable String sessionId) {
        return proxyPost("/api/v1/quiz/sessions/" + sessionId + "/next-question", null);
    }

    /** POST /quiz/sessions/{sessionId}/answers — 답변 제출 */
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
