#!/bin/bash
set -e

mkdir -p ~/finswipe

# systemd 서비스 등록
sudo tee /etc/systemd/system/finswipe.service > /dev/null << 'EOF'
[Unit]
Description=FinSwipe Spring Boot Backend
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/finswipe
EnvironmentFile=/home/ubuntu/finswipe/.env
ExecStart=/usr/bin/java -Xmx256m -Xms128m -jar /home/ubuntu/finswipe/app.jar
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=finswipe

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable finswipe

echo "=== systemd 서비스 등록 완료 ==="
sudo systemctl status finswipe --no-pager || true
