package com.finswipe.controller;

import com.finswipe.dto.response.HealthResponse;
import com.finswipe.service.AnalyzerService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
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
    public ResponseEntity<Map<String, String>> healthDetail() {
        String dbStatus = checkDb();
        String chatTableStatus = checkTable("chat_messages");
        Map<String, String> genai = analyzerService.checkHealth();
        String genaiStatus = genai.getOrDefault("status", "offline");
        String overall = "ok".equals(dbStatus) && "ok".equals(genaiStatus) ? "ok" : "degraded";
        return ResponseEntity.ok(Map.of(
                "status", overall, "db", dbStatus,
                "genai", genaiStatus, "chat_table", chatTableStatus));
    }

    private String checkTable(String tableName) {
        try {
            // pg_tables는 information_schema보다 권한 제한이 없음
            Integer pgCount = jdbcTemplate.queryForObject(
                    "SELECT COUNT(*) FROM pg_tables WHERE tablename = ?",
                    Integer.class, tableName);
            if (pgCount != null && pgCount > 0) return "ok";

            // Flyway 히스토리에서 해당 테이블 관련 migration 상태 조회
            try {
                List<Map<String, Object>> rows = jdbcTemplate.queryForList(
                        "SELECT version, description, success FROM flyway_schema_history " +
                        "WHERE description ILIKE ? ORDER BY installed_rank DESC LIMIT 5",
                        "%" + tableName + "%");
                if (rows.isEmpty()) return "missing(no-flyway-record)";
                return "missing(flyway:" + rows.stream()
                        .map(r -> "v" + r.get("version") + "=" + r.get("success"))
                        .reduce((a, b) -> a + "," + b).orElse("?") + ")";
            } catch (Exception fe) {
                return "missing(flyway-err:" + fe.getClass().getSimpleName() + ")";
            }
        } catch (Exception e) {
            return "error:" + e.getClass().getSimpleName();
        }
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
