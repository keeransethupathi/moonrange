#!/bin/bash
# setup_do_proxy.sh - Simple SOCKS5 Proxy for DigitalOcean (using microsocks)
# 
# Instructions:
# 1. SSH into your DigitalOcean Droplet
# 2. Upload/Paste this file as 'setup_do_proxy.sh'
# 3. Run: chmod +x setup_do_proxy.sh && sudo ./setup_do_proxy.sh [username] [password]
# 4. Use: socks5://username:password@IP:1080

set -e

USER_NAME=${1:-"moonrange"}
USER_PASS=${2:-"moonrange123"}

echo "--- Installing build dependencies ---"
sudo apt-get update
sudo apt-get install -y build-essential git

echo "--- Building microsocks ---"
git clone https://github.com/rofl0r/microsocks.git
cd microsocks
make
sudo make install

echo "--- Creating systemd service ---"
cat <<EOF | sudo tee /etc/systemd/system/microsocks.service
[Unit]
Description=Microsocks SOCKS5 Proxy
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/microsocks -1 -p 1080 -u ${USER_NAME} -P ${USER_PASS}
Restart=always

[Install]
WantedBy=multi-user.target
EOF

echo "--- Starting microsocks ---"
sudo systemctl daemon-reload
sudo systemctl enable microsocks
sudo systemctl start microsocks

echo "--- Done! ---"
echo "Proxy listening on port 1080"
echo "Credentials: ${USER_NAME}:${USER_PASS}"
echo "--------------------------------------------------------"
echo "IMPORTANT: Make sure to open port 1080 in DigitalOcean Firewall!"
echo "Check your outbound IP using: curl -4 https://api.ipify.org"
echo "--------------------------------------------------------"
