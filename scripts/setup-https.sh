#!/bin/bash
# EC2 최초 1회 실행 — HTTPS 설정 (Nginx + Certbot)
# 사용법: bash scripts/setup-https.sh
set -e

DOMAIN="finswipe.co.kr"
EMAIL="swj0718820@gmail.com"

echo "=== 1. Nginx + Certbot 설치 ==="
sudo apt-get update -y
sudo apt-get install -y nginx certbot python3-certbot-nginx

echo "=== 2. certbot 인증용 webroot 디렉터리 ==="
sudo mkdir -p /var/www/certbot

echo "=== 3. Nginx 임시 설정 (80번 포트만, 인증서 발급 전) ==="
sudo tee /etc/nginx/sites-available/finswipe <<'EOF'
server {
    listen 80;
    server_name finswipe.co.kr www.finswipe.co.kr;
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }
    location / {
        return 200 'ok';
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/finswipe /etc/nginx/sites-enabled/finswipe
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

echo "=== 4. Let's Encrypt 인증서 발급 ==="
sudo certbot certonly \
    --webroot -w /var/www/certbot \
    -d "$DOMAIN" -d "www.$DOMAIN" \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email

echo "=== 5. 실제 Nginx 설정 적용 ==="
sudo cp ~/finswipe/nginx/finswipe.conf /etc/nginx/sites-available/finswipe
sudo nginx -t && sudo systemctl reload nginx

echo "=== 6. 인증서 자동 갱신 타이머 활성화 ==="
sudo systemctl enable certbot.timer
sudo systemctl start certbot.timer

echo ""
echo "완료! https://www.finswipe.co.kr 접속 확인하세요."
