package com.finswipe.controller;

import com.finswipe.dto.response.HealthResponse;
import com.finswipe.service.AnalyzerService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

@RestController
@RequiredArgsConstructor
@Slf4j
public class HealthController {

    private final AnalyzerService analyzerService;
    private final JdbcTemplate jdbcTemplate;

    /** Zeabur 기본 health probe가 / 를 치는 경우 대응 */
    @GetMapping("/")
    public ResponseEntity<Map<String, String>> root() {
        return ResponseEntity.ok(Map.of("status", "ok"));
    }

    /** Zeabur health probe용 — DB만 확인 (빠른 응답) */
    @GetMapping("/health")
    public ResponseEntity<HealthResponse> health() {
        String dbStatus = checkDb();
        String overall = "ok".equals(dbStatus) ? "ok" : "degraded";
        return ResponseEntity.ok(new HealthResponse(overall, dbStatus, "unknown"));
    }

    /** 관리자용 상세 헬스체크 — GenAI 포함 (느릴 수 있음) */
    @GetMapping("/health/detail")
    public ResponseEntity<HealthResponse> healthDetail() {
        String dbStatus = checkDb();
        Map<String, String> genai = analyzerService.checkHealth();
        String genaiStatus = genai.getOrDefault("status", "offline");
        String overall = "ok".equals(dbStatus) && "ok".equals(genaiStatus) ? "ok" : "degraded";
        return ResponseEntity.ok(new HealthResponse(overall, dbStatus, genaiStatus));
    }

    private String checkDb() {
        try {
            jdbcTemplate.queryForObject("SELECT 1", Integer.class);
            return "ok";
        } catch (Exception e) {
            log.warn("DB health check failed: {}", e.getMessage());
            return "error";
        }
    }
}
