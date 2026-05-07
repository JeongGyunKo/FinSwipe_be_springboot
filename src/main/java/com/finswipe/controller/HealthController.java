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

    @GetMapping("/health")
    public ResponseEntity<HealthResponse> health() {
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
