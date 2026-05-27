package com.finswipe.dto.response;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.AllArgsConstructor;
import lombok.Getter;

import java.util.Map;

@Getter
@AllArgsConstructor
@JsonInclude(JsonInclude.Include.NON_NULL)
public class JobStatusResponse {

    private final String jobId;
    private final String name;
    private final String status;
    private final String createdAt;
    private final String startedAt;
    private final String finishedAt;
    private final Map<String, Object> result;
    private final String error;
}
