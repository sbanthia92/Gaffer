#!/usr/bin/env bash
# EC2 User Data bootstrap — runs once on first boot of any new instance.
# Installs system packages, CloudWatch agent, and prepares the directory
# structure. The CD workflow handles code deploy + service start.
set -euo pipefail

APP_DIR="/home/ec2-user/gaffer"
VENV_DIR="$APP_DIR/.venv"
STATIC_DIR="/var/www/gaffer"
LOG_DIR="/var/log/gaffer"
REPO="https://github.com/sbanthia92/Gaffer.git"

# ── System packages ────────────────────────────────────────────────────────────
dnf update -y
dnf install -y python3.11 python3.11-pip git nginx amazon-cloudwatch-agent

# Node 20
curl -fsSL https://rpm.nodesource.com/setup_20.x | bash -
dnf install -y nodejs

# Certbot
pip3.11 install certbot certbot-nginx

# ── Directory structure ────────────────────────────────────────────────────────
mkdir -p "$STATIC_DIR" "$LOG_DIR"
chown ec2-user:ec2-user "$LOG_DIR"

# ── Clone repo ─────────────────────────────────────────────────────────────────
git clone "$REPO" "$APP_DIR"
chown -R ec2-user:ec2-user "$APP_DIR"

# ── Python virtualenv ──────────────────────────────────────────────────────────
sudo -u ec2-user python3.11 -m venv "$VENV_DIR"
sudo -u ec2-user "$VENV_DIR/bin/pip" install --upgrade pip -q
sudo -u ec2-user "$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt" -q
sudo -u ec2-user "$VENV_DIR/bin/pip" install -e "$APP_DIR" -q

# ── CloudWatch agent ───────────────────────────────────────────────────────────
mkdir -p /opt/aws/amazon-cloudwatch-agent/etc
cat > /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json << 'EOF'
{
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/var/log/gaffer/app.log",
            "log_group_name": "/gaffer/production/api",
            "log_stream_name": "{instance_id}",
            "timestamp_format": "%Y-%m-%dT%H:%M:%S",
            "timezone": "UTC",
            "multi_line_start_pattern": "^\\{"
          }
        ]
      }
    }
  }
}
EOF

/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config -m ec2 -s \
  -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json

systemctl enable amazon-cloudwatch-agent

# ── systemd service ────────────────────────────────────────────────────────────
cat > /etc/systemd/system/gaffer.service << EOF
[Unit]
Description=The Gaffer — FastAPI server
After=network.target

[Service]
User=ec2-user
WorkingDirectory=$APP_DIR
Environment=ENVIRONMENT=production
ExecStart=$VENV_DIR/bin/uvicorn server.main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=5
StandardOutput=append:$LOG_DIR/app.log
StandardError=append:$LOG_DIR/app.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable gaffer
# Service starts after CD deploys code and configures nginx+HTTPS
