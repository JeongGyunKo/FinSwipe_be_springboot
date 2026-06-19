package com.finswipe.service;

import com.finswipe.config.AppProperties;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.mail.javamail.MimeMessageHelper;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
@Slf4j
public class EmailService {

    private final JavaMailSender mailSender;
    private final AppProperties props;

    @Async
    public void sendVerificationEmail(String to, String token) {
        String link = props.getAuth().getAppBaseUrl() + "/auth/verify-email?token=" + token;
        String html = """
                <div style="font-family: sans-serif; max-width: 480px; margin: 0 auto;">
                  <h2>FinSwipe 이메일 인증</h2>
                  <p>아래 버튼을 클릭해 이메일 인증을 완료해주세요.</p>
                  <a href="%s"
                     style="display:inline-block;padding:12px 24px;background:#3b82f6;
                            color:#fff;border-radius:8px;text-decoration:none;font-weight:600;">
                    이메일 인증하기
                  </a>
                  <p style="color:#6b7fa3;font-size:13px;margin-top:16px;">
                    링크는 24시간 동안 유효합니다.
                  </p>
                </div>
                """.formatted(link);
        send(to, "[FinSwipe] 이메일 인증", html);
    }

    @Async
    public void sendPasswordResetEmail(String to, String token) {
        String link = props.getAuth().getFrontendBaseUrl() + "/reset-password?token=" + token;
        String html = """
                <div style="font-family: sans-serif; max-width: 480px; margin: 0 auto;">
                  <h2>FinSwipe 비밀번호 재설정</h2>
                  <p>아래 버튼을 클릭해 새 비밀번호를 설정해주세요.</p>
                  <a href="%s"
                     style="display:inline-block;padding:12px 24px;background:#ef4444;
                            color:#fff;border-radius:8px;text-decoration:none;font-weight:600;">
                    비밀번호 재설정
                  </a>
                  <p style="color:#6b7fa3;font-size:13px;margin-top:16px;">
                    링크는 1시간 동안 유효합니다. 본인이 요청하지 않은 경우 무시해주세요.
                  </p>
                </div>
                """.formatted(link);
        send(to, "[FinSwipe] 비밀번호 재설정", html);
    }

    private void send(String to, String subject, String html) {
        try {
            var message = mailSender.createMimeMessage();
            var helper = new MimeMessageHelper(message, true, "UTF-8");
            helper.setTo(to);
            helper.setSubject(subject);
            helper.setText(html, true);
            mailSender.send(message);
            log.info("[메일] 발송 완료: to={} subject={}", to, subject);
        } catch (Exception e) {
            log.error("[메일] 발송 실패: to={} error={}", to, e.getMessage());
        }
    }
}
