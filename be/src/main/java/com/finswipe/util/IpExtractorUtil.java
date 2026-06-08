package com.finswipe.util;

import jakarta.servlet.http.HttpServletRequest;

public class IpExtractorUtil {

    private IpExtractorUtil() {}

    /**
     * 실제 클라이언트 IP 추출.
     * X-Real-IP를 우선 사용 (nginx가 원본 IP로 덮어씀, 스푸핑 불가).
     * X-Forwarded-For는 클라이언트가 임의 값을 주입해 레이트 리밋 우회에 악용될 수 있으므로 사용하지 않음.
     */
    public static String extractRealIp(HttpServletRequest request) {
        String realIp = request.getHeader("X-Real-IP");
        if (realIp != null && !realIp.isBlank()) {
            return realIp.trim();
        }
        return request.getRemoteAddr();
    }
}
