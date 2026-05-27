package com.finswipe.job;

import lombok.Getter;
import lombok.Setter;

import java.time.Instant;
import java.util.Map;

@Getter
@Setter
public class JobInfo {

    private final String jobId;
    private final String name;
    private JobStatus status;
    private final Instant createdAt;
    private Instant startedAt;
    private Instant finishedAt;
    private Map<String, Object> result;
    private String error;

    public JobInfo(String jobId, String name) {
        this.jobId = jobId;
        this.name = name;
        this.status = JobStatus.PENDING;
        this.createdAt = Instant.now();
    }
}
