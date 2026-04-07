#!/bin/bash
# setup_oracle_streamlit.sh - Set up Streamlit and Python 3.9+ on Oracle Linux 9
# This script handles Python, Venv, and Chromium dependencies for Selenium.

set -e

echo "--- Updating system & installing EPEL ---"
sudo dnf update -y
sudo dnf install -y oracle-epel-release-el9

echo "--- Installing Python 3.11 & Development Tools ---"
sudo dnf install -y python3.11 python3.11-pip python3.11-devel git

echo "--- Installing Chromium & ChromeDriver (for Selenium) ---"
sudo dnf install -y chromium chromium-common

# Note: chromium-chromedriver might be part of chromium or separate
if ! command -v chromedriver &> /dev/null; then
    sudo dnf install -y chromium-chromedriver || echo "Warning: chromedriver not found in package manager"
fi

echo "--- Setting up Application Directory ---"
APP_DIR="/home/opc/moon_range"
if [ ! -d "$APP_DIR" ]; then
    mkdir -p "$APP_DIR"
fi

echo "--- Creating Python Virtual Environment ---"
python3.11 -m venv "$APP_DIR/venv"
source "$APP_DIR/venv/bin/activate"

echo "--- Installing Python Dependencies ---"
pip install --upgrade pip
pip install -r "$APP_DIR/requirements.txt"

echo "--- Configuring Streamlit systemd Service ---"
cat <<EOF | sudo tee /etc/systemd/system/streamlit.service
[Unit]
Description=MoonRange Streamlit App
After=network.target

[Service]
User=opc
WorkingDirectory=$APP_DIR
Environment="PATH=$APP_DIR/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=$APP_DIR/venv/bin/streamlit run streamlit_app.py --server.port 8501 --server.address 0.0.0.0
Restart=always

[Install]
WantedBy=multi-user.target
EOF

echo "--- Starting Streamlit Service ---"
sudo systemctl daemon-reload
sudo systemctl enable streamlit
sudo systemctl restart streamlit

echo "--- Configuring OS Firewall for Port 8501 ---"
if command -v firewall-cmd &> /dev/null; then
    sudo firewall-cmd --permanent --add-port=8501/tcp
    sudo firewall-cmd --reload
    echo "Firewalld updated for port 8501"
fi

# Fallback for iptables
sudo iptables -I INPUT 1 -p tcp --dport 8501 -j ACCEPT

echo "--------------------------------------------------------"
echo "✅ Streamlit setup complete!"
echo "App URL:  http://$(curl -s -4 https://api.ipify.org):8501"
echo "--------------------------------------------------------"
echo "⚠️  REMINDER: You MUST also open Port 8501 in the"
echo "Oracle Cloud Console (Security Lists -> Ingress Rules)."
echo "--------------------------------------------------------"
