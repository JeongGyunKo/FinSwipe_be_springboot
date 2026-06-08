package com.finswipe.dto.request;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

public record GoogleAuthRequest(@NotBlank @Size(max = 4096) String idToken) {}
