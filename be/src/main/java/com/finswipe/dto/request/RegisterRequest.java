package com.finswipe.dto.request;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

public record RegisterRequest(
        @NotBlank @Email String email,
        @NotBlank @Size(min = 8, max = 64, message = "비밀번호는 8~64자여야 합니다") String password,
        @NotBlank @Size(min = 2, max = 30) String displayName
) {}
