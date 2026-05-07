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

    private static final long RETENTION_SECONDS = 7200; // 2시간

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

    // 완료된 오래된 작업 정리 (2시간 후)
    @Scheduled(fixedDelay = 600_000)
    public void cleanupOldJobs() {
        Instant cutoff = Instant.now().minusSeconds(RETENTION_SECONDS);
        store.entrySet().removeIf(entry -> {
            JobInfo job = entry.getValue();
            boolean finished = job.getStatus() == JobStatus.DONE || job.getStatus() == JobStatus.FAILED;
            return finished && job.getFinishedAt() != null && job.getFinishedAt().isBefore(cutoff);
        });
    }
}
