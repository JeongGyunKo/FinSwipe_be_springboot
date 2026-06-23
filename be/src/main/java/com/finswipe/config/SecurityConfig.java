package com.finswipe.config;

import com.finswipe.filter.AdminKeyAuthFilter;
import com.finswipe.filter.JwtAuthFilter;
import com.finswipe.filter.SwaggerBasicAuthFilter;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.Customizer;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

@Configuration
@EnableWebSecurity
@RequiredArgsConstructor
public class SecurityConfig {

    private final JwtAuthFilter jwtAuthFilter;
    private final AppProperties props;

    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http
            .cors(Customizer.withDefaults())
            .csrf(AbstractHttpConfigurer::disable)
            .formLogin(AbstractHttpConfigurer::disable)
            .httpBasic(AbstractHttpConfigurer::disable)
            .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            // X-Frame-Options는 SecurityHeadersFilter에서 경로별로 직접 제어
            .headers(h -> h.frameOptions(fo -> fo.disable()))
            .authorizeHttpRequests(auth -> auth
                // 공개 엔드포인트
                .requestMatchers("/", "/health", "/health/detail").permitAll()
                .requestMatchers("/auth/**").permitAll()
                .requestMatchers(HttpMethod.GET, "/news/genai/health").permitAll()
                .requestMatchers("/swagger-ui/**", "/v3/api-docs/**").permitAll()
                .requestMatchers("/preview.html", "/admin.html", "/digest.html", "/card-preview.html").permitAll()
                // 어드민 (X-Admin-Key 별도 검증)
                .requestMatchers("/news/collect", "/news/reanalyze", "/news/reset-insights",
                        "/news/analyze/**", "/news/diagnose", "/news/test", "/news/jobs/**").permitAll()
                .requestMatchers("/admin/**").permitAll()
                // 인증 필요
                .requestMatchers("/user/**").authenticated()
                .requestMatchers("/quiz/**").permitAll()
                .requestMatchers("/analysis/**").authenticated()
                .requestMatchers("/chat/**").authenticated()
                .requestMatchers(HttpMethod.GET, "/news/latest", "/news/search", "/news/tickers",
                        "/news/tickers/*/sentiment-trend", "/news/article/*").authenticated()
                .requestMatchers(HttpMethod.POST, "/news/*/read").authenticated()
                .requestMatchers(HttpMethod.POST, "/news/device-token").authenticated()
                .requestMatchers(HttpMethod.DELETE, "/news/device-token").authenticated()
                .requestMatchers(HttpMethod.GET, "/news/notification-settings").authenticated()
                .requestMatchers(HttpMethod.PUT, "/news/notification-settings").authenticated()
                // 명시되지 않은 모든 경로 차단 (기본값 공개 방지)
                .anyRequest().denyAll()
            )
            .exceptionHandling(ex -> ex
                // JWT 없음/만료 → 401 (기존 Spring Security 기본값 403이 사용자에게 버그처럼 보임)
                .authenticationEntryPoint((req, res, e) -> {
                    res.setContentType("application/json;charset=UTF-8");
                    res.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
                    res.getWriter().write("{\"error\":\"인증이 필요합니다.\"}");
                })
                // 인증됐지만 권한 없음 → 403 유지
                .accessDeniedHandler((req, res, e) -> {
                    res.setContentType("application/json;charset=UTF-8");
                    res.setStatus(HttpServletResponse.SC_FORBIDDEN);
                    res.getWriter().write("{\"error\":\"접근 권한이 없습니다.\"}");
                })
            )
            // 스웨거 문서(/swagger-ui, /v3/api-docs)는 Basic 인증(비번 환경변수)으로 보호 — 미설정 시 전면 차단
            .addFilterBefore(new SwaggerBasicAuthFilter(props), UsernamePasswordAuthenticationFilter.class)
            // 어드민 도구(admin.html 등)가 X-Admin-Key로 뉴스 조회 read에 접근 — 뉴스 read 경로 전용, 일반 뉴스만
            .addFilterBefore(new AdminKeyAuthFilter(props), UsernamePasswordAuthenticationFilter.class)
            .addFilterBefore(jwtAuthFilter, UsernamePasswordAuthenticationFilter.class);

        return http.build();
    }

    @Bean
    public BCryptPasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }
}
