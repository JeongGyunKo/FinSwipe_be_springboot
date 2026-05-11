package com.finswipe.util;

import jakarta.servlet.http.HttpServletRequest;

public class IpExtractorUtil {

    private IpExtractorUtil() {}

    /**
     * 실제 클라이언트 IP 추출.
     * X-Real-IP를 우선 사용 (nginx가 원본 IP로 덮어씀, 스푸핑 불가).
     * X-Forwarded-For는 클라이언트가 임의 값을 주입할 수 있어 rate limit 우회에 악용될 수 있음.
     */
    public static String extractRealIp(HttpServletRequest request) {
        String realIp = request.getHeader("X-Real-IP");
        if (realIp != null && !realIp.isBlank()) {
            return realIp.trim();
        }
        String forwarded = request.getHeader("X-Forwarded-For");
        if (forwarded != null && !forwarded.isBlank()) {
            return forwarded.split(",")[0].trim();
        }
        return request.getRemoteAddr();
    }
}
