package com.finswipe.dto.request;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

public record ResetPasswordRequest(
        @NotBlank @Size(max = 128) String token,
        @NotBlank @Size(min = 8, max = 64) String newPassword
) {}
