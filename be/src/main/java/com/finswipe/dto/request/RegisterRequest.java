package com.finswipe.dto.request;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

public record RegisterRequest(
        @NotBlank @Email @Size(max = 254) String email,
        @NotBlank
        @Size(min = 8, max = 64, message = "비밀번호는 8~64자여야 합니다")
        @Pattern(
            regexp = "^(?=.*[a-z])(?=.*[0-9]).+$",
            message = "비밀번호는 영문 소문자와 숫자를 포함해야 합니다"
        )
        String password,
        @NotBlank @Size(min = 2, max = 30) String displayName,
        @NotBlank @Size(min = 3, max = 30)
        @Pattern(regexp = "^[a-zA-Z0-9_]+$", message = "아이디는 영문, 숫자, 밑줄(_)만 사용할 수 있습니다")
        String loginId
) {}
