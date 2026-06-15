package com.finswipe.config;

import com.finswipe.filter.JwtAuthFilter;
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
                .requestMatchers(HttpMethod.GET, "/news/latest", "/news/tickers", "/news/search",
                        "/news/tickers/*/sentiment-trend", "/news/genai/health").permitAll()
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
                .requestMatchers(HttpMethod.POST, "/news/*/read").authenticated()
                .requestMatchers(HttpMethod.POST, "/news/device-token").authenticated()
                .requestMatchers(HttpMethod.DELETE, "/news/device-token").authenticated()
                .requestMatchers(HttpMethod.GET, "/news/notification-settings").authenticated()
                .requestMatchers(HttpMethod.PUT, "/news/notification-settings").authenticated()
                // 명시되지 않은 모든 경로 차단 (기본값 공개 방지)
                .anyRequest().denyAll()
            )
            .addFilterBefore(jwtAuthFilter, UsernamePasswordAuthenticationFilter.class);

        return http.build();
    }

    @Bean
    public BCryptPasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }
}
