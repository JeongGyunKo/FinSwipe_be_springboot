package com.finswipe.util;

import jakarta.servlet.http.HttpServletRequest;

public class IpExtractorUtil {

    private IpExtractorUtil() {}

    /**
     * X-Forwarded-For 헤더에서 실제 클라이언트 IP 추출 (reverse proxy 환경 대응)
     */
    public static String extractRealIp(HttpServletRequest request) {
        String forwarded = request.getHeader("X-Forwarded-For");
        if (forwarded != null && !forwarded.isBlank()) {
            return forwarded.split(",")[0].trim();
        }
        return request.getRemoteAddr();
    }
}
