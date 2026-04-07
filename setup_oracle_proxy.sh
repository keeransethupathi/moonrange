#!/bin/bash
# setup_oracle_proxy.sh - SOCKS5 Proxy for Oracle Cloud (Oracle Linux 9)
# Optimized for Oracle Linux / RHEL / CentOS

set -e

USER_NAME=${1:-"moonrange"}
USER_PASS=${2:-"moonrange123"}
PORT=1080

echo "--- Installing build dependencies & firewall tools ---"
sudo dnf update -y
sudo dnf groupinstall -y "Development Tools"
sudo dnf install -y git

echo "--- Building microsocks ---"
sudo rm -rf microsocks
git clone https://github.com/rofl0r/microsocks.git
cd microsocks
make
sudo make install

echo "--- Configuring systemd service ---"
cat <<EOF | sudo tee /etc/systemd/system/microsocks.service
[Unit]
Description=Microsocks SOCKS5 Proxy
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/microsocks -1 -p ${PORT} -u ${USER_NAME} -P ${USER_PASS}
Restart=always

[Install]
WantedBy=multi-user.target
EOF

echo "--- Starting microsocks ---"
sudo systemctl daemon-reload
sudo systemctl enable microsocks
sudo systemctl restart microsocks

echo "--- Configuring OS Firewall (Oracle Linux Specific) ---"
if command -v firewall-cmd &> /dev/null; then
    sudo firewall-cmd --permanent --add-port=${PORT}/tcp
    sudo firewall-cmd --reload
    echo "Firewalld updated for port ${PORT}"
fi

# Fallback for raw iptables if firewalld is not active
sudo iptables -I INPUT 1 -p tcp --dport ${PORT} -j ACCEPT

echo "--------------------------------------------------------"
echo "✅ DONE! Proxy is now running on port ${PORT}"
echo "--------------------------------------------------------"
echo "Credentials: ${USER_NAME} : ${USER_PASS}"
echo "Public IP:   \$(curl -s -4 https://api.ipify.org)"
echo "User:        opc"
echo "--------------------------------------------------------"
echo "⚠️  REMINDER: You MUST also open Port ${PORT} in the"
echo "Oracle Cloud Console (Security Lists -> Ingress Rules)."
echo "--------------------------------------------------------"
