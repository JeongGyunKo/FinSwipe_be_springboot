# FinSwipe GenAI Server

FinSwipe 금융 앱의 AI 분석 서버입니다.  
Python 3.11 + FastAPI + Anthropic Claude API로 구축되었습니다.

## 기능

| 기능 | 설명 |
|------|------|
| 🎯 **사용자 레벨 테스트** | 금융 지식 퀴즈로 레벨 1~5 측정 (Gemini, 적응형 난이도) |
| 📰 **레벨 맞춤 뉴스 분석** | 티커별 오늘 뉴스를 사용자 수준에 맞게 요약 |
| 🤖 **FinBERT 감성 분석** | 로컬 모델 (ProsusAI/finbert) — 금융 도메인 특화 |
| 🔍 **LIME XAI** | 감성 판단 근거 문장/키워드 추출 (로컬) |
| 🇰🇷 **한국어 현지화** | Gemini로 3줄 요약 + 한국어 번역 |

## AI 파이프라인

```
기사 입력
  │
  ├─ FinBERT (로컬) ──→ sentiment label + score
  ├─ LIME (로컬)    ──→ xai {keywords, highlights}
  └─ Gemini 2.5    ──→ summary_3lines (영문) + localized {title, summary_3lines} (한국어)
```

## API 엔드포인트

```
GET  /health                           서버 상태 확인
POST /news/analyze                     단일 기사 분석
GET  /news/summary/{ticker}?level=3    티커별 뉴스 요약 (레벨 맞춤)
POST /quiz/start                       퀴즈 세션 시작
GET  /quiz/question/{session_id}       다음 문제 가져오기
POST /quiz/answer                      답변 제출
GET  /quiz/result/{session_id}         최종 레벨 결과
POST /api/v1/articles/enrich-text      Spring Boot 호환 레거시 API
```

Swagger UI: `http://localhost:8000/docs`

## 로컬 개발 환경 설정

### 요구사항
- Python 3.11+
- PostgreSQL (AWS RDS 또는 로컬)

### 설치

```bash
cd genai

# 가상 환경 생성 (권장)
python -m venv venv
source venv/bin/activate      # macOS/Linux
venv\Scripts\activate         # Windows

# 의존성 설치
pip install -r requirements.txt

# 환경변수 설정
cp .env.example .env
# .env 파일을 열어 ANTHROPIC_API_KEY, DB_URL 등을 입력
```

### DB 마이그레이션

Spring Boot Flyway가 자동으로 `migrations/V4__add_level_quiz_tables.sql`을 실행합니다.  
또는 psql로 직접 실행:

```bash
psql $DB_URL -f migrations/V4__add_level_quiz_tables.sql
```

### 서버 실행

```bash
cd genai
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## EC2 배포

### 전제 조건
- EC2 인스턴스 (Ubuntu 22.04 권장)
- Python 3.11+ 설치됨
- Spring Boot 서버가 이미 실행 중 (포트 8080)

### 배포 절차

#### 1. 코드 배포

```bash
# EC2 접속
ssh -i ~/.ssh/your-key.pem ubuntu@your-ec2-ip

# 코드 업데이트
cd /home/ubuntu/FinSwipe_be_springboot
git pull

# Python 가상 환경 설정
cd genai
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

#### 2. 환경변수 설정

```bash
sudo nano /etc/genai.env
```

```env
ANTHROPIC_API_KEY=sk-ant-api03-...
DB_URL=postgresql://your-rds-host.rds.amazonaws.com:5432/finswipe_db
DB_USERNAME=postgres
DB_PASSWORD=your_password
PORT=8001
CORS_ORIGINS=*
```

```bash
sudo chmod 600 /etc/genai.env
```

#### 3. systemd 서비스 등록

```bash
sudo nano /etc/systemd/system/finswipe-genai.service
```

```ini
[Unit]
Description=FinSwipe GenAI Server
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/FinSwipe_be_springboot/genai
EnvironmentFile=/etc/genai.env
ExecStart=/home/ubuntu/FinSwipe_be_springboot/genai/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8001
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable finswipe-genai
sudo systemctl start finswipe-genai
sudo systemctl status finswipe-genai
```

#### 4. Spring Boot 환경변수 업데이트

`/etc/finswipe.env` (또는 Spring Boot의 환경변수)에 GenAI 서버 URL 설정:

```env
GENAI_URL=http://localhost:8001
```

Spring Boot의 `application.yml` 또는 `AppProperties`에서 이 값을 참조하면 됩니다.

#### 5. 포트 확인

EC2 보안 그룹에서 8001 포트는 내부(Spring Boot)에서만 접근하도록 제한 권장:
- Inbound: 8080 (Spring Boot, public), 8001 (GenAI, 내부 only 또는 Nginx 뒤)

### 로그 확인

```bash
sudo journalctl -u finswipe-genai -f
```

## 퀴즈 플로우

```
POST /quiz/start
  → {session_id}

GET /quiz/question/{session_id}
  → {question_id, question, choices, ...}

POST /quiz/answer
  → {is_correct, explanation, new_difficulty, is_finished, final_level}
  
  (is_finished=false이면 GET /quiz/question/{session_id} 반복)

GET /quiz/result/{session_id}
  → {final_level, accuracy_percent, questions[...]}
```

### 레벨 기준

| 레벨 | 설명 | 난이도 범위 |
|------|------|------------|
| 1 | 입문자 — 주식 기초 | 1.0 ~ 1.9 |
| 2 | 초보자 — 기본 용어 | 2.0 ~ 2.9 |
| 3 | 중급자 — PER/PBR | 3.0 ~ 3.9 |
| 4 | 고급자 — 재무제표 분석 | 4.0 ~ 4.9 |
| 5 | 전문가 — 매크로경제 | 5.0 |

## 비용 최적화

- **FinBERT + LIME 로컬 실행**: 감성 분석·XAI는 API 비용 없음 (GPU 선택사항, CPU로도 동작)
- **Gemini는 요약·번역·퀴즈만**: LLM 호출을 최소화
- **텍스트 길이 제한**: 기사 본문 최대 6000자 (Gemini), 청크 단위 448토큰 (FinBERT)

## 환경변수 참조

| 변수 | 필수 | 설명 |
|------|------|------|
| `ANTHROPIC_API_KEY` | ✅ | Anthropic API 키 |
| `DB_URL` | ✅ | PostgreSQL DSN (`postgresql://...`) |
| `DB_USERNAME` | ✅ | DB 사용자명 |
| `DB_PASSWORD` | ✅ | DB 비밀번호 |
| `PORT` | | 서버 포트 (기본: 8000) |
| `CORS_ORIGINS` | | 허용 오리진 (기본: *) |
| `CLAUDE_MODEL` | | Claude 모델 (기본: claude-opus-4-7) |
| `DB_POOL_MIN` | | 최소 커넥션 수 (기본: 2) |
| `DB_POOL_MAX` | | 최대 커넥션 수 (기본: 10) |
