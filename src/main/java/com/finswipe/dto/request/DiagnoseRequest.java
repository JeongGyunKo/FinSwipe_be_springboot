package com.finswipe.dto.request;

import jakarta.validation.constraints.NotBlank;
import lombok.Getter;

@Getter
public class DiagnoseRequest {

    @NotBlank
    private String sourceUrl;
}
