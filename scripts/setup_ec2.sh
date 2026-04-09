#!/usr/bin/env bash
# One-time bootstrap for the Gaffer EC2 instance (Amazon Linux 2023).
# Run as ec2-user after first SSH:
#   bash scripts/setup_ec2.sh <YOUR_ELASTIC_IP>
#
# What this does:
#   1. Installs Python 3.11, Node 20, nginx, certbot
#   2. Clones the repo and installs dependencies
#   3. Creates /etc/gaffer/.env (you fill in the secrets)
#   4. Builds the React UI
#   5. Configures nginx with the-gaffer.io + HTTPS via Let's Encrypt
#   6. Creates and enables the gaffer systemd service
set -euo pipefail

ELASTIC_IP="${1:?Usage: setup_ec2.sh <ELASTIC_IP>}"
DOMAIN="the-gaffer.io"
REPO="https://github.com/sbanthia92/Gaffer.git"
APP_DIR="/home/ec2-user/gaffer"
VENV_DIR="$APP_DIR/.venv"
STATIC_DIR="/var/www/gaffer"

echo "==> Setting up Gaffer on $DOMAIN"

# ── System packages ────────────────────────────────────────────────────────────
echo "==> Installing system packages..."
sudo dnf update -y
sudo dnf install -y python3.11 python3.11-pip git nginx

# Node 20 via NodeSource
curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo bash -
sudo dnf install -y nodejs

# Certbot via pip (most reliable on AL2023)
sudo pip3.11 install certbot certbot-nginx

# ── Clone repo ─────────────────────────────────────────────────────────────────
echo "==> Cloning repo..."
if [ -d "$APP_DIR" ]; then
  git -C "$APP_DIR" pull
else
  git clone "$REPO" "$APP_DIR"
fi

# ── Python virtualenv + dependencies ──────────────────────────────────────────
echo "==> Installing Python dependencies..."
python3.11 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"
"$VENV_DIR/bin/pip" install -e "$APP_DIR"

# ── Secrets ────────────────────────────────────────────────────────────────────
echo "==> Creating /etc/gaffer/.env..."
sudo mkdir -p /etc/gaffer
if [ ! -f /etc/gaffer/.env ]; then
  sudo tee /etc/gaffer/.env > /dev/null <<'ENV'
ANTHROPIC_API_KEY=your_key_here
PINECONE_API_KEY=your_key_here
PINECONE_INDEX_NAME=the-gaffer
API_SPORTS_KEY=your_key_here
FPL_TEAM_ID=your_team_id_here
ENVIRONMENT=production
ENV
  echo "!!! Fill in /etc/gaffer/.env with your real secrets before starting the service !!!"
else
  echo "    /etc/gaffer/.env already exists, skipping."
fi

# ── Build React UI ─────────────────────────────────────────────────────────────
echo "==> Building React UI..."
cd "$APP_DIR/ui" && npm ci && npm run build
sudo mkdir -p "$STATIC_DIR"
sudo cp -r "$APP_DIR/ui/dist/." "$STATIC_DIR/"

# ── nginx config ───────────────────────────────────────────────────────────────
echo "==> Configuring nginx (HTTP only — certbot will upgrade to HTTPS)..."
sudo tee /etc/nginx/conf.d/gaffer.conf > /dev/null <<NGINX
server {
    listen 80;
    server_name $DOMAIN;

    root $STATIC_DIR;
    index index.html;

    location / {
        try_files \$uri \$uri/ /index.html;
    }

    location /api/ {
        proxy_pass         http://127.0.0.1:8000/;
        proxy_http_version 1.1;
        proxy_set_header   Host              \$host;
        proxy_set_header   X-Real-IP         \$remote_addr;
        proxy_set_header   X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_read_timeout 200s;
        proxy_send_timeout 200s;
    }
}
NGINX

# Remove default nginx config
sudo rm -f /etc/nginx/conf.d/default.conf
sudo nginx -t
sudo systemctl enable nginx
sudo systemctl restart nginx

# ── HTTPS via Let's Encrypt ────────────────────────────────────────────────────
echo "==> Obtaining Let's Encrypt certificate for $DOMAIN..."
sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "admin@$DOMAIN" --redirect

# ── systemd service ────────────────────────────────────────────────────────────
echo "==> Creating gaffer systemd service..."
sudo mkdir -p /var/log/gaffer
sudo chown ec2-user:ec2-user /var/log/gaffer

sudo tee /etc/systemd/system/gaffer.service > /dev/null <<SERVICE
[Unit]
Description=The Gaffer — FastAPI server
After=network.target

[Service]
User=ec2-user
WorkingDirectory=$APP_DIR
EnvironmentFile=/etc/gaffer/.env
ExecStart=$VENV_DIR/bin/uvicorn server.main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=5
StandardOutput=append:/var/log/gaffer/app.log
StandardError=append:/var/log/gaffer/app.log

[Install]
WantedBy=multi-user.target
SERVICE

sudo systemctl daemon-reload
sudo systemctl enable gaffer

echo ""
echo "================================================================"
echo " Setup complete!"
echo " 1. Fill in secrets: sudo nano /etc/gaffer/.env"
echo " 2. Start the server: sudo systemctl start gaffer"
echo " 3. Check status:     sudo systemctl status gaffer"
echo " 4. Your app will be at: https://$DOMAIN"
echo "================================================================"
