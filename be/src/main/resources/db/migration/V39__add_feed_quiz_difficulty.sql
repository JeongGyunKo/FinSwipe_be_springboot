-- V36: 피드 삽입용 적응형 퀴즈 난이도 컬럼
-- 온보딩 퀴즈(user_profiles.level)와는 별개 트랙. 3.0(중간)에서 시작해 답변마다 미세 조정.
-- 정답 +0.34 / 오답 -0.5, 범위 1.0~5.0 (컨트롤러에서 갱신). NULL = 아직 미시작 → 3.0으로 취급.
ALTER TABLE user_profiles
    ADD COLUMN IF NOT EXISTS feed_quiz_difficulty DOUBLE PRECISION;
