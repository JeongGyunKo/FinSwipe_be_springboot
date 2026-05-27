#!/bin/bash
# EC2 초기 설정 스크립트 — Ubuntu 22.04/24.04 기준
# 사용법: sudo bash ec2-init.sh

set -e

CURRENT_USER=${SUDO_USER:-$(whoami)}
APP_DIR="/home/$CURRENT_USER/finswipe"

echo "=== [1/5] Docker 설치 ==="
if command -v docker &> /dev/null; then
    echo "Docker 이미 설치됨: $(docker --version)"
else
    apt-get update -q
    apt-get install -y ca-certificates curl
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
        https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        | tee /etc/apt/sources.list.d/docker.list > /dev/null
    apt-get update -q
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

echo "=== [2/5] Docker 서비스 시작 ==="
systemctl enable docker
systemctl start docker

echo "=== [3/5] $CURRENT_USER → docker 그룹 추가 ==="
usermod -aG docker "$CURRENT_USER"

echo "=== [4/5] 앱 디렉토리 및 설정 파일 생성 ==="
mkdir -p "$APP_DIR"

# docker-compose.yml 생성
cat > "$APP_DIR/docker-compose.yml" << 'EOF'
services:
  app:
    image: ghcr.io/jeonggyunko/finswipe_be_springboot:latest
    container_name: finswipe-app
    restart: unless-stopped
    ports:
      - "8080:8080"
    env_file:
      - .env
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-files: "3"
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
EOF

# .env 템플릿 생성 (값이 없으면 경고)
if [ ! -f "$APP_DIR/.env" ]; then
    cat > "$APP_DIR/.env" << 'EOF'
# DB (AWS RDS)
DB_URL=jdbc:postgresql://YOUR-RDS-ENDPOINT.rds.amazonaws.com:5432/finswipe_db
DB_USERNAME=postgres
DB_PASSWORD=CHANGE_ME

# Finlight
FINLIGHT_API_KEY=CHANGE_ME

# GenAI
GENAI_URL=http://CHANGE_ME:8000
GENAI_USER=CHANGE_ME
GENAI_PASSWORD=CHANGE_ME

# Admin
ADMIN_API_KEY=CHANGE_ME

# CORS (쉼표 구분, 프로토콜 포함)
CORS_ORIGINS=https://your-frontend-domain.com

# FCM (필요 시)
FCM_SERVICE_ACCOUNT_JSON=
FCM_PROJECT_ID=
FCM_CLIENT_EMAIL=
FCM_PRIVATE_KEY=

# 로그
LOG_LEVEL=INFO
EOF
    echo ".env 템플릿 생성됨 → $APP_DIR/.env 를 실제 값으로 수정하세요"
else
    echo ".env 이미 존재, 건너뜀"
fi

chown -R "$CURRENT_USER:$CURRENT_USER" "$APP_DIR"

echo "=== [5/5] 완료 ==="
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  다음 단계"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "1) .env 파일 편집:"
echo "   nano $APP_DIR/.env"
echo ""
echo "2) GitHub Secrets 등록 (레포 → Settings → Secrets → Actions):"
echo "   EC2_HOST      = $(curl -s --connect-timeout 3 ifconfig.me || echo '<EC2 퍼블릭 IP>')"
echo "   EC2_USERNAME  = $CURRENT_USER"
echo "   EC2_SSH_KEY   = (다운받은 .pem 파일 내용 전체)"
echo "   GHCR_TOKEN    = (GitHub PAT — read:packages 권한 필요)"
echo "                   https://github.com/settings/tokens/new"
echo ""
echo "3) AWS 보안 그룹에서 인바운드 규칙 추가:"
echo "   포트 8080  TCP  0.0.0.0/0  (앱)"
echo "   포트 22    TCP  내 IP      (SSH)"
echo ""
echo "4) 로그아웃 후 재로그인 (docker 그룹 적용)"
echo ""
echo "설정 완료 후 GitHub master 브랜치에 push하면 자동 배포됩니다."
