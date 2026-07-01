package com.finswipe.controller;

import com.fasterxml.jackson.annotation.JsonProperty;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.ExampleObject;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.BatchPreparedStatementSetter;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.sql.Types;
import java.util.List;
import java.util.Map;
import java.util.Set;

@Tag(name = "Events", description = "행동 신호 수집 — 카드 노출·체류시간 등. 개인화 큐레이션 학습용. 좋아요/싫어요/읽음은 각 전용 엔드포인트 사용.")
@RestController
@RequestMapping("/events")
@RequiredArgsConstructor
@Slf4j
public class EventController {

    private final JdbcTemplate jdbc;

    private static final Set<String> ALLOWED_TYPES = Set.of("impression", "dwell", "open", "skip");
    private static final int MAX_BATCH = 200;

    @Operation(summary = "행동 이벤트 배치 수집",
            description = "FE가 카드 노출(impression)·체류(dwell, dwell_ms 포함)·열람(open)·건너뜀(skip)을 모아 전송. "
                    + "허용 type 외/유효하지 않은 article_id는 조용히 무시. 한 번에 최대 200건.")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            { "ok": true, "saved": 12 }
            """)))
    @SecurityRequirement(name = "bearerAuth")
    @PostMapping("/batch")
    public ResponseEntity<Map<String, Object>> batch(Authentication auth,
                                                     @RequestBody(required = false) EventBatchRequest body) {
        final String uid = (auth != null && auth.getPrincipal() instanceof java.util.UUID)
                ? auth.getPrincipal().toString() : null;
        if (uid == null) return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body(Map.of("ok", false));
        if (body == null || body.events() == null || body.events().isEmpty()) {
            return ResponseEntity.ok(Map.of("ok", true, "saved", 0));
        }

        List<Event> valid = body.events().stream()
                .filter(e -> e != null && e.type() != null && ALLOWED_TYPES.contains(e.type())
                        && e.articleId() != null && isValidUuid(e.articleId()))
                .limit(MAX_BATCH)
                .toList();
        if (valid.isEmpty()) return ResponseEntity.ok(Map.of("ok", true, "saved", 0));

        try {
            jdbc.batchUpdate("""
                    INSERT INTO user_card_events (user_id, article_id, event_type, dwell_ms)
                    VALUES (CAST(? AS UUID), CAST(? AS UUID), ?, ?)
                    """, new BatchPreparedStatementSetter() {
                @Override
                public void setValues(PreparedStatement ps, int i) throws SQLException {
                    Event e = valid.get(i);
                    ps.setString(1, uid);
                    ps.setString(2, e.articleId());
                    ps.setString(3, e.type());
                    if (e.dwellMs() != null && e.dwellMs() >= 0) ps.setInt(4, e.dwellMs());
                    else ps.setNull(4, Types.INTEGER);
                }

                @Override
                public int getBatchSize() { return valid.size(); }
            });
            return ResponseEntity.ok(Map.of("ok", true, "saved", valid.size()));
        } catch (Exception ex) {
            log.error("[이벤트] 배치 저장 실패: {}", ex.getMessage());
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(Map.of("ok", false));
        }
    }

    private static boolean isValidUuid(String value) {
        try { java.util.UUID.fromString(value); return true; }
        catch (IllegalArgumentException e) { return false; }
    }

    record EventBatchRequest(List<Event> events) {}

    record Event(String type,
                 @JsonProperty("article_id") String articleId,
                 @JsonProperty("dwell_ms") Integer dwellMs) {}
}
