package com.finswipe.controller;

import com.finswipe.config.AppProperties;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.security.MessageDigest;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Tag(name = "Guardrail", description = "AI 안전장치 현황 및 평가 지표 (어드민 전용)")
@RestController
@RequestMapping("/admin/guardrail")
@RequiredArgsConstructor
@Slf4j
public class GuardrailController {

    private final JdbcTemplate jdbc;
    private final AppProperties props;

    @Operation(summary = "AI 가드레일 현황", description = "안전장치 목록, 평가 지표, 필터링 통계")
    @GetMapping
    public ResponseEntity<Map<String, Object>> guardrail(
            @RequestHeader("X-Admin-Key") String adminKey) {
        requireAdmin(adminKey);

        Map<String, Object> result = new LinkedHashMap<>();

        // ── 안전장치 목록 ──────────────────────────────────────────────
        result.put("guardrails", List.of(
            Map.of("name", "뉴스 중복 탐지",      "type", "input_filter",   "detail", "제목 75% + 본문 앞 300자 65% Jaccard 유사도 (동일 티커 기사 한정)"),
            Map.of("name", "최소 본문 길이",        "type", "input_filter",   "detail", "300자 미만 기사 제외 (3줄 요약 품질 보장)"),
            Map.of("name", "Transcript 필터",       "type", "input_filter",   "detail", "conference call / earnings transcript 제외"),
            Map.of("name", "암호화폐 티커 제외",   "type", "input_filter",   "detail", "BTC/ETH 등 61종 코인 티커 필터"),
            Map.of("name", "3회 재시도 제한",       "type", "retry_guard",    "detail", "분석 실패 기사 최대 3회 재시도 후 제외"),
            Map.of("name", "Gemini 503 재시도",     "type", "api_guard",      "detail", "서버 오류 시 3초 후 1회 자동 재시도"),
            Map.of("name", "JWT 인증",               "type", "auth_guard",     "detail", "사용자 API 접근 시 JWT 필수 검증"),
            Map.of("name", "Rate Limiting",          "type", "auth_guard",     "detail", String.format("공개 %d RPM / 어드민 %d RPM / 퀴즈 %d RPM",
                    props.getRateLimit().getPublicRpm(), props.getRateLimit().getAdminRpm(), props.getRateLimit().getQuizRpm())),
            Map.of("name", "퀴즈 정답 위치 셔플",  "type", "bias_guard",     "detail", "LLM의 A번 편향 방지 — 매 문제 랜덤 셔플"),
            Map.of("name", "Gemini 금지 문제 유형","type", "quality_guard",  "detail", "성향형/주관형 문제 생성 명시적 차단")
        ));

        // ── 평가 지표 (AI 품질) ────────────────────────────────────────
        try {
            Map<String, Object> eval = new LinkedHashMap<>();

            // 감성 분석 분포
            List<Map<String, Object>> sentimentDist = jdbc.queryForList(
                    "SELECT sentiment_label, COUNT(*) as cnt FROM news_articles WHERE sentiment_label IS NOT NULL GROUP BY sentiment_label ORDER BY cnt DESC");
            eval.put("sentiment_distribution", sentimentDist);

            // 분석 완료율
            Long total = jdbc.queryForObject("SELECT COUNT(*) FROM news_articles WHERE content IS NOT NULL", Long.class);
            Long analyzed = jdbc.queryForObject("SELECT COUNT(*) FROM news_articles WHERE sentiment_reason IS NOT NULL", Long.class);
            eval.put("analysis_completion_rate", total != null && total > 0
                    ? String.format("%.1f%%", analyzed * 100.0 / total) : "N/A");

            // 퀴즈 평균 정답률
            Map<String, Object> quizEval = jdbc.queryForMap(
                    "SELECT AVG(CASE WHEN is_correct THEN 1.0 ELSE 0.0 END) as avg_correct, COUNT(*) as total_answers FROM quiz_questions WHERE question_type = 'multiple_choice' AND is_correct IS NOT NULL");
            Double avgCorrect = (Double) quizEval.get("avg_correct");
            eval.put("quiz_avg_correct_rate", avgCorrect != null ? String.format("%.1f%%", avgCorrect * 100) : "N/A");
            eval.put("quiz_total_answers", quizEval.get("total_answers"));

            // 영역별 평균 점수
            List<Map<String, Object>> areaScores = jdbc.queryForList(
                    "SELECT area, ROUND(AVG(CASE WHEN is_correct THEN 5.0 ELSE 0.0 END)::NUMERIC, 1) as avg_score, COUNT(*) as cnt FROM quiz_questions WHERE question_type = 'multiple_choice' AND area IS NOT NULL AND is_correct IS NOT NULL GROUP BY area ORDER BY avg_score DESC");
            eval.put("quiz_area_scores", areaScores);

            result.put("ai_evaluation", eval);
        } catch (Exception e) {
            log.error("[guardrail] ai_evaluation 조회 오류", e);
            result.put("ai_evaluation", Map.of("error", "조회 오류"));
        }

        // ── 필터링 효과 측정 ──────────────────────────────────────────
        try {
            Map<String, Object> filter = new LinkedHashMap<>();
            Long cleanFiltered = jdbc.queryForObject(
                    "SELECT COUNT(*) FROM news_articles WHERE sentiment_label = '_clean_filtered'", Long.class);
            Long total = jdbc.queryForObject("SELECT COUNT(*) FROM news_articles", Long.class);
            filter.put("clean_filtered_count", cleanFiltered);
            filter.put("filter_rate", total != null && total > 0
                    ? String.format("%.1f%%", cleanFiltered * 100.0 / total) : "N/A");
            result.put("filter_stats", filter);
        } catch (Exception e) {
            log.error("[guardrail] filter_stats 조회 오류", e);
            result.put("filter_stats", Map.of("error", "조회 오류"));
        }

        return ResponseEntity.ok(result);
    }

    private void requireAdmin(String key) {
        String expected = props.getAdmin().getApiKey();
        if (!MessageDigest.isEqual(key.getBytes(java.nio.charset.StandardCharsets.UTF_8), expected.getBytes(java.nio.charset.StandardCharsets.UTF_8))) {
            throw new org.springframework.web.server.ResponseStatusException(
                    org.springframework.http.HttpStatus.FORBIDDEN, "Invalid admin key");
        }
    }
}
