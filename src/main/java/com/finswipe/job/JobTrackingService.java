package com.finswipe.job;

import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

@Service
public class JobTrackingService {

    private static final long RETENTION_SECONDS = 7200;  // 완료 작업 보관 2시간
    private static final long STUCK_SECONDS     = 3600;  // PENDING/RUNNING 1시간 이상 → stuck으로 간주

    private final ConcurrentHashMap<String, JobInfo> store = new ConcurrentHashMap<>();

    public String createJob(String name) {
        String jobId = UUID.randomUUID().toString().substring(0, 8);
        store.put(jobId, new JobInfo(jobId, name));
        return jobId;
    }

    public void startJob(String jobId) {
        JobInfo job = store.get(jobId);
        if (job != null) {
            job.setStatus(JobStatus.RUNNING);
            job.setStartedAt(Instant.now());
        }
    }

    public void finishJob(String jobId, Map<String, Object> result) {
        JobInfo job = store.get(jobId);
        if (job != null) {
            job.setStatus(JobStatus.DONE);
            job.setFinishedAt(Instant.now());
            job.setResult(result);
        }
    }

    public void failJob(String jobId, String error) {
        JobInfo job = store.get(jobId);
        if (job != null) {
            job.setStatus(JobStatus.FAILED);
            job.setFinishedAt(Instant.now());
            job.setError(error);
        }
    }

    public Optional<JobInfo> getJob(String jobId) {
        return Optional.ofNullable(store.get(jobId));
    }

    // 10분마다 오래된 작업 정리
    @Scheduled(fixedDelay = 600_000)
    public void cleanupOldJobs() {
        Instant completedCutoff = Instant.now().minusSeconds(RETENTION_SECONDS);
        Instant stuckCutoff     = Instant.now().minusSeconds(STUCK_SECONDS);
        store.entrySet().removeIf(entry -> {
            JobInfo job = entry.getValue();
            if (job.getStatus() == JobStatus.DONE || job.getStatus() == JobStatus.FAILED) {
                return job.getFinishedAt() != null && job.getFinishedAt().isBefore(completedCutoff);
            }
            // PENDING/RUNNING이 1시간 이상 → 스레드 소멸 등 stuck 상태로 판단
            return job.getCreatedAt().isBefore(stuckCutoff);
        });
    }
}
