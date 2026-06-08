package com.finswipe.dto.request;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.Getter;

@Getter
public class DiagnoseRequest {

    @NotBlank
    @Size(max = 2048)
    private String sourceUrl;
}
