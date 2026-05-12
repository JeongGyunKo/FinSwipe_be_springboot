package com.finswipe.scheduler;

import com.finswipe.service.NewsCollectorService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
@Slf4j
public class NewsScheduler {

    private final NewsCollectorService collectorService;

    // 15분마다 뉴스 수집 (Python: APScheduler 15min interval)
    @Scheduled(fixedDelay = 900_000, initialDelay = 10_000)
    public void collectMarketNews() {
        log.info("[Scheduler] Starting market news collection");
        try {
            collectorService.collectMarketNews();
        } catch (Exception e) {
            log.error("[Scheduler] News collection failed", e);
        }
    }

    // 1분마다 미분석 기사 재분석
    @Scheduled(fixedDelay = 60_000, initialDelay = 30_000)
    public void reanalyzeUnanalyzed() {
        Thread.ofVirtual().start(() -> {
            try {
                int count = collectorService.reanalyzeUnanalyzed(20);
                if (count > 0) {
                    log.info("[Scheduler] Re-analyzed {} articles", count);
                } else {
                    log.debug("[Scheduler] Re-analysis skipped (running or no articles)");
                }
            } catch (Exception e) {
                log.error("[Scheduler] Re-analysis failed", e);
            }
        });
    }

    // 6시간마다 오래된 기사 정리 (Python: APScheduler 6hr interval)
    @Scheduled(fixedDelay = 21_600_000, initialDelay = 60_000)
    public void cleanupOldContent() {
        log.info("[Scheduler] Starting cleanup of old articles");
        try {
            collectorService.cleanupOldContent();
        } catch (Exception e) {
            log.error("[Scheduler] Cleanup failed", e);
        }
    }
}
