import streamlit as st
import json
import pandas as pd
import numpy as np
import time
import os
import requests
import pyotp
import sys
import threading
import subprocess
import traceback
import logging
import re
from datetime import datetime
from SmartApi.smartWebSocketV2 import SmartWebSocketV2
from custom_tv_chart import renderCustomLightweightCharts
from order import place_flattrade_order

# ================= STREAMLIT CONFIG =================
st.set_page_config(layout="wide", page_title="AngelOne Intelligence Hub")

STOP_FILE = "stop_indices.txt"

def safe_get_secret(key, default=None):
    """Safely get a secret from streamlit secrets or environment variables."""
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.environ.get(key, default)

def fetch_live_indices():
    file_path = "flattrade_indices.json"
    if os.path.exists(file_path):
        try:
            with open(file_path, "r") as f:
                data = json.load(f)
                if time.time() - data.get("last_update", 0) < 60:
                    return data.get("prices", {})
        except:
            pass
    return {"NIFTY 50": {"lp": "N/A", "pc": "0.00"}, "SENSEX": {"lp": "N/A", "pc": "0.00"}}

def launch_indices_backend(force=False):
    if not force and os.path.exists(STOP_FILE):
        return # Respect manual stop

    file_path = "flattrade_indices.json"
    last_update = 0
    if os.path.exists(file_path):
        try:
            with open(file_path, "r") as f:
                last_update = json.load(f).get("last_update", 0)
        except:
            pass
    
    if force or (time.time() - last_update > 60):
        try:
            # Check if auth exists (file or secret)
            has_auth = os.path.exists("flattrade_auth.json") or safe_get_secret("FT_TOKEN")
            if has_auth:
                cmd = [sys.executable, "flattrade_indices.py"]
                if sys.platform == "win32":
                    subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE)
                else:
                    # Linux (Streamlit Cloud)
                    subprocess.Popen(cmd, start_new_session=True)
                return True
        except Exception as e:
            print(f"Launch error: {e}")
    return False

@st.fragment(run_every="1s")
def indices_banner_fragment():
    try:
        live_indices = fetch_live_indices()
        
        # Live control toggle
        is_stopped = os.path.exists(STOP_FILE)
        btn_label = "▶️ Start Live Indices" if is_stopped else "🛑 Stop Live Indices"
        btn_help = "Start the indices background service" if is_stopped else "Stop the indices background service"
        
        if st.button(btn_label, help=btn_help, use_container_width=True):
            if is_stopped:
                # Force start: Clear stop flag and stale PID
                if os.path.exists(STOP_FILE):
                    os.remove(STOP_FILE)
                if os.path.exists("flattrade_indices.pid"):
                    try:
                        os.remove("flattrade_indices.pid")
                    except:
                        pass
                launch_indices_backend(force=True)
            else:
                with open(STOP_FILE, "w") as f:
                    f.write("stop")
            st.rerun()

        cols = st.columns(2)
        for i, (label, data) in enumerate(live_indices.items()):
            with cols[i]:
                price = data.get("lp", "N/A")
                change = f"{data.get('pc', '0.00')}%"
                st.metric(label, price, delta=change)
    except Exception as e:
        st.error(f"Error loading live indices: {e}")

@st.fragment(run_every="1s")
def display_dashboard_fragment(token_id, exchange_type, exchange_mapping):
    # Data Sync
    DATA_FILE = "market_data.json"
    data = {}
    data_found = False
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r") as f:
                data = json.load(f)
            
            last_update = data.get("last_update", 0)
            if time.time() - last_update < 10:
                st.session_state.backend_running = True
                
                # Apply IST offset (+5:30) for chart display
                IST_OFFSET = 19800 # 5.5 hours in seconds
                st.session_state.ohlc_data = [{**b, "time": b["time"] + IST_OFFSET} for b in data.get("ohlc", [])]
                st.session_state.ema_data = [{**b, "time": b["time"] + IST_OFFSET} for b in data.get("ema", [])]
                
                # Supertrend needs special handling to format the colors for the chart based on the trend
                st_data_raw = data.get("supertrend", [])
                st_formatted = []
                for b in st_data_raw:
                    # Color the line green for uptrend (1), red for downtrend (-1)
                    color = '#4caf50' if b.get('trend', 1) == 1 else '#f44336'
                    st_formatted.append({"time": b["time"] + IST_OFFSET, "value": b["value"], "color": color})
                
                st.session_state.supertrend_data = st_formatted
                
                st.session_state.current_ltp = float(data.get("ltp", 0.0))
                st.session_state.live_ema = float(data.get("live_ema", 0.0))
                st.session_state.live_strend = float(data.get("live_strend", 0.0))
                st.session_state.live_trend = data.get("live_trend", 1)
                st.session_state.last_data_ts = last_update
                data_found = True
            else:
                st.session_state.backend_running = False
    except Exception as fe:
        print(f"Local Sync Error: {fe}")

    # Layout
    col1, col2, col3 = st.columns(3)
    ltp = st.session_state.current_ltp
    ohlc = st.session_state.ohlc_data
    ema = st.session_state.get("ema_data", [])
    strend = st.session_state.get("supertrend_data", [])
    
    # Use live unclosed indicators if available, else fallback to last closed bar
    latest_ema = st.session_state.get("live_ema", 0.0)
    if latest_ema == 0.0 and ema:
        latest_ema = ema[-1]['value']
        
    latest_strend = st.session_state.get("live_strend", 0.0)
    if latest_strend == 0.0 and strend:
        latest_strend = strend[-1]['value']
    
    col1.metric("Price", f"₹{ltp:,.2f}")
    col2.metric("EMA (200)", f"₹{latest_ema:,.2f}")
    col3.metric("Supertrend", f"₹{latest_strend:,.2f}")
    
    if ohlc:
        chart_options = {
            "height": 500,
            "layout": {
                "background": {"type": 'solid', "color": '#0e1117'},
                "textColor": '#d1d4dc',
                "fontSize": 10
            },
            "grid": {"vertLines": {"color": "#242733"}, "horzLines": {"color": "#242733"}},
            "timeScale": {"timeVisible": True, "secondsVisible": True, "borderColor": '#485c7b'},
        }
        series = [{"type": 'Candlestick', "data": ohlc, "options": {"upColor": '#26a69a', "downColor": '#ef5350'}}]
        if ema:
            series.append({"type": 'Line', "data": ema, "options": {"color": '#2962FF', "lineWidth": 2, "title": 'EMA 200'}})
        if strend:
            # We use a Line series that supports individual point colors
            series.append({"type": 'Line', "data": strend, "options": {"lineWidth": 2, "title": 'Supertrend'}})
        
        # Rendering directly in the fragment (without .empty()) reduces flicker
        renderCustomLightweightCharts([{"chart": chart_options, "series": series}], 'integrated_chart')
        
        st.divider()
        col1, _ = st.columns([1, 3])
        with col1:
            csv_df = pd.DataFrame(ohlc)
            if not csv_df.empty:
                # Revert IST offset applied earlier (+19800) for downloading clean UTC data
                IST_OFFSET = 19800
                csv_df['time'] = pd.to_datetime(csv_df['time'] - IST_OFFSET, unit='s')
                csv_df['time'] = csv_df['time'].dt.tz_localize('UTC').dt.tz_convert('Asia/Kolkata')
                csv = csv_df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Download Chart Data (CSV)",
                    data=csv,
                    file_name=f"market_data_{token_id}.csv",
                    mime="text/csv",
                    use_container_width=True
                )
    else:
        st.info("Connected. Waiting for the first Range 1R bar...")
            
    # Trading logic is consolidated in the automation_monitor fragment in 'Order Portal'
    # to avoid duplicate executions and ensure consistent state management.

    if not data_found:
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r") as f:
                    offline_data = json.load(f)
                if time.time() - offline_data.get("last_update", 0) < 10:
                    st.info("Live data detected locally. Connecting...")
                    st.session_state.backend_running = True
                    st.rerun()
            except:
                pass
        st.info("System Offline. Start backend in sidebar or ensure it's running.")

# ================= UI Styling =================

# UI Styling
st.markdown("""
<style>
    .main { background-color: #0e1117; color: #d1d4dc; }
    .stMetric { background-color: #161b22; padding: 10px; border-radius: 8px; border: 1px solid #30363d; }
    [data-testid="stMetricValue"] { font-size: 1.5rem !important; }
    [data-testid="stMetricLabel"] { font-size: 0.8rem !important; }
    h1 { font-size: 1.8rem !important; }
</style>
""", unsafe_allow_html=True)

# ================= STATE MANAGEMENT =================
if 'ohlc_data' not in st.session_state:
    st.session_state.ohlc_data = []
if 'ema_data' not in st.session_state:
    st.session_state.ema_data = []
if 'supertrend_data' not in st.session_state:
    st.session_state.supertrend_data = []
if 'live_ema' not in st.session_state:
    st.session_state.live_ema = 0.0
if 'live_strend' not in st.session_state:
    st.session_state.live_strend = 0.0
if 'live_trend' not in st.session_state:
    st.session_state.live_trend = 1
if 'current_ltp' not in st.session_state:
    st.session_state.current_ltp = 0.0
if 'backend_running' not in st.session_state:
    st.session_state.backend_running = False
if 'last_error' not in st.session_state:
    st.session_state.last_error = None
if 'auto_trading_active' not in st.session_state:
    st.session_state.auto_trading_active = False
if 'trading_logs' not in st.session_state:
    st.session_state.trading_logs = []
if 'last_order_side' not in st.session_state:
    st.session_state.last_order_side = None

# Scrip Master & Dashboard Sync State
if 'selected_expiry' not in st.session_state:
    st.session_state.selected_expiry = None
if 'selected_instrument' not in st.session_state:
    st.session_state.selected_instrument = None
if 'selected_strike' not in st.session_state:
    st.session_state.selected_strike = None
if 'dashboard_token' not in st.session_state:
    st.session_state.dashboard_token = "864149"
if 'dashboard_exchange' not in st.session_state:
    st.session_state.dashboard_exchange = "BFO"
if 'trade_tsym_input' not in st.session_state:
    st.session_state.trade_tsym_input = "NIFTY24FEB26C26000"
if 'trade_exch_input' not in st.session_state:
    st.session_state.trade_exch_input = "NFO"
if 'dashboard_range' not in st.session_state:
    st.session_state.dashboard_range = 0.05

# Automation Strategy State
if 'trading_phase' not in st.session_state:
    st.session_state.trading_phase = 'BUY' # Starts with BUY
if 'last_order_price' not in st.session_state:
    st.session_state.last_order_price = 0.0

# Silence ScriptRunContext and other warnings
logging.getLogger("streamlit.runtime.scriptrunner").setLevel(logging.ERROR)
logging.getLogger("smartWebSocketV2").setLevel(logging.ERROR)

# ================= UI =================
st.title("🛡️ AngelOne Intelligence Hub")

# Sidebar Menu for Navigation
with st.sidebar:
    st.header(" NAVIGATION")
    menu = st.radio("Go to", ["📊 Dashboard", "🔐 Login Portal", "📈 Flattrade Login", "📦 Order Portal", "📦 Scrip Master"])
    st.divider()

if menu == "📊 Dashboard":
    with st.sidebar:
        st.header("Systems Control")
        
        # Selection UI
        exchange_mapping = {"NSE": 1, "NFO": 2, "MCX": 5, "BSE": 3, "CDS": 13, "BFO": 4}
        exch_list = list(exchange_mapping.keys())
        default_idx = exch_list.index(st.session_state.dashboard_exchange) if st.session_state.dashboard_exchange in exch_list else 2
        
        selected_exchange_name = st.selectbox("Exchange", options=exch_list, index=default_idx, key="dash_exch")
        st.session_state.dashboard_exchange = selected_exchange_name
        exchange_type = exchange_mapping[selected_exchange_name]
        
        token_id = st.text_input("Token ID", value=st.session_state.dashboard_token, key="dash_token")
        st.session_state.dashboard_token = token_id
        
        range_val = st.number_input("Range 1R Size", value=float(st.session_state.get('dashboard_range', 0.05)), step=0.05, format="%.2f", key="dash_range")
        st.session_state.dashboard_range = range_val
        
        st.divider()
        
        if not st.session_state.backend_running:
            if st.button("🚀 Start Backend System", type="primary"):
                if not os.path.exists("auth.json"):
                    st.error("Authentication file `auth.json` not found. Please login via 'Login Portal' first.")
                else:
                    with open("auth.json", "r") as f:
                        auth_data = json.load(f)
                    
                    # Ensure API Key is present (might be in secrets)
                    if "api_key" not in auth_data:
                        auth_data["api_key"] = safe_get_secret("ANGEL_API_KEY")
                    
                    if not auth_data.get("api_key"):
                        st.error("AngelOne API Key not found in auth.json or secrets.")
                    else:
                        # START BACKEND via Subprocess (External Process)
                        # First check if it's already actually online locally
                        is_already_online = False
                        DATA_FILE = "market_data.json"
                        if os.path.exists(DATA_FILE):
                            try:
                                with open(DATA_FILE, "r") as f:
                                    data = json.load(f)
                                if time.time() - data.get("last_update", 0) < 10:
                                    is_already_online = True
                            except:
                                pass
                        
                        if is_already_online:
                            st.warning(f"Backend for {token_id} is already running locally.")
                        else:
                            import subprocess
                            python_exe = sys.executable
                            cmd = [python_exe, "backend.py", str(exchange_type), str(token_id), str(range_val)]
                            
                            # Launch backend.py as a separate process in a new console
                            subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0)
                            st.success(f"System Launching for {selected_exchange_name}:{token_id} with Range {range_val}...")
                        
                        st.session_state.backend_running = True
                        time.sleep(2)
                        st.rerun()
        else:
            if st.button("🛑 Stop Backend System"):
                # Signal stop via file (backend.py checks for STOP_FILE)
                STOP_FILE = "stop_backend.txt"
                with open(STOP_FILE, "w") as f:
                    f.write("stop")
                st.session_state.backend_running = False
                st.warning("Stop signal sent to backend.")
                time.sleep(1)
                st.rerun()
                
        st.write(f"**System Status:** {'🟢 ONLINE' if st.session_state.backend_running else '🔴 OFFLINE'}")
        
        if st.session_state.last_error:
            st.error(f"Last Error: {st.session_state.last_error}")
            if st.button("Clear Error"):
                st.session_state.last_error = None
                st.rerun()
        
        if st.button("🗑️ Reset Data"):
            st.session_state.ohlc_data = []
            st.session_state.ema_data = []
            st.session_state.supertrend_data = []
            st.session_state.live_ema = 0.0
            st.session_state.live_strend = 0.0
            st.session_state.current_ltp = 0.0
            st.rerun()

    # Call Fragment for Live Updates
    display_dashboard_fragment(token_id, exchange_type, exchange_mapping)

elif menu == "🔐 Login Portal": # Login Portal
    st.header("🔐 AngelOne Login")
    
    existing_auth = {}
    if os.path.exists("auth.json"):
        with open("auth.json", "r") as f:
            existing_auth = json.load(f)

    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        with st.form("login_form"):
            default_c_code = existing_auth.get("client_code") or safe_get_secret("ANGEL_CLIENT_CODE", "K135836")
            default_api_k = existing_auth.get("api_key") or safe_get_secret("ANGEL_API_KEY", "t0bsCNdW")
            default_totp_s = safe_get_secret("ANGEL_TOTP_SECRET", "YGDC6I7VDV7KJSIELCN626FKBY")

            c_code = st.text_input("Client Code", value=default_c_code)
            pwd = st.text_input("Password", type="password", value="1997")
            api_k = st.text_input("API Key", value=default_api_k)
            totp_s = st.text_input("TOTP Secret", value=default_totp_s)
            
            submit = st.form_submit_button("LOGIN", type="primary", use_container_width=True)
            
            if submit:
                try:
                    totp = pyotp.TOTP(totp_s)
                    current_code = totp.now()
                    url = "https://apiconnect.angelone.in/rest/auth/angelbroking/user/v1/loginByPassword"
                    
                    payload = {"clientcode": c_code, "password": pwd, "totp": current_code, "state": "12345"}
                    headers = {
                        'Content-Type': 'application/json', 'Accept': 'application/json',
                        'X-UserType': 'USER', 'X-SourceID': 'WEB',
                        'X-ClientLocalIP': '127.0.0.1', 'X-ClientPublicIP': '127.0.0.1',
                        'X-MACAddress': 'MAC_ADDRESS', 'X-PrivateKey': api_k
                    }
                    
                    with st.spinner("Logging in..."):
                        response = requests.post(url, headers=headers, data=json.dumps(payload))
                    
                    if response.status_code == 200:
                        resp_json = response.json()
                        if resp_json.get('status'):
                            jwt_token = "Bearer " + resp_json['data']['jwtToken']
                            save_data = {
                                "Authorization": jwt_token, "api_key": api_k,
                                "feedtoken": resp_json['data']['feedToken'], "client_code": c_code
                            }
                            with open("auth.json", "w") as f:
                                json.dump(save_data, f, indent=4)
                            st.success("Login Successful!")
                            st.balloons()
                        else:
                            st.error(f"Login Failed: {resp_json.get('message')}")
                    else:
                        st.error(f"HTTP Error {response.status_code}")
                except Exception as e:
                    st.error(f"Error: {e}")

elif menu == "📈 Flattrade Login": # Flattrade Login
    st.header("📈 Flattrade Login")
    
    API_KEY = safe_get_secret("FT_API_KEY", "b5768d873c474155a3d09d56a50f5314")
    API_SECRET = safe_get_secret("FT_API_SECRET", "2025.3bb14ae6afd04844b10e338a6f388a9c7416205cb6990c69")
    AUTH_URL = f"https://auth.flattrade.in/?app_key={API_KEY}"
    TOKEN_URL = "https://authapi.flattrade.in/trade/apitoken"

    # Automated Login Section
    st.subheader("🤖 Automated Login")
    st.info("Click the button below to automatically login and generate your access token.")
    
    if st.button("🚀 Run Auto Login", type="primary", use_container_width=True):
        try:
            from auto_login import auto_login, generate_access_token
            
            with st.status("Running automated login...") as status:
                log_placeholder = st.empty()
                logs = []
                
                def ui_logger(msg):
                    logs.append(msg)
                    with log_placeholder.container():
                        for m in logs[-5:]: # Show last 5 lines for focus
                            st.write(f"› {m}")

                # Try loading from secrets/env first via auto_login's internal logic
                # or check if credentials.json exists as fallback
                has_secrets = safe_get_secret('FT_USERNAME') is not None
                if not os.path.exists('credentials.json') and not has_secrets:
                    st.error("No credentials found. Please set FT environment variables / secrets or provide `credentials.json`.")
                else:
                    result = auto_login(headless=True, log_func=ui_logger)
                    
                    if result["status"] == "success":
                        request_code = result["code"]
                        st.write(f"✅ Captured request code: `{request_code[:10]}...`")
                        
                        st.write("Generating final access token...")
                        token = generate_access_token(request_code)
                        
                        if token:
                            st.success("Access token generated successfully!")
                            st.code(token, language="text")
                            
                            flat_auth = {"api_key": API_KEY, "token": token}
                            with open("flattrade_auth.json", "w") as f:
                                json.dump(flat_auth, f, indent=4)
                            st.info("Token saved to `flattrade_auth.json`")
                            status.update(label="Login Successful!", state="complete")
                        else:
                            st.error("Failed to generate access token from code.")
                            status.update(label="Token Generation Failed", state="error")
                    else:
                        st.error(f"Automation failed: {result.get('message')}")
                        status.update(label="Automation Failed", state="error")
        except Exception as e:
            st.error(f"An unexpected error occurred: {e}")
            st.exception(e)

    st.divider()
    
    # Credential Manager
    with st.expander("🔐 Credential Manager"):
        st.write("Update your Flattrade credentials below. Changes will be saved to `credentials.json`.")
        
        # Load current credentials
        curr_creds = {}
        if os.path.exists('credentials.json'):
            try:
                with open('credentials.json', 'r') as f:
                    curr_creds = json.load(f)
            except:
                pass
        
        with st.form("credential_manager_form"):
            new_user = st.text_input("Username", value=curr_creds.get('username', ''))
            new_pass = st.text_input("Password", value=curr_creds.get('password', ''), type="password")
            new_totp = st.text_input("TOTP Key", value=curr_creds.get('totp_key', ''), type="password")
            
            if st.form_submit_button("💾 UPDATE CREDENTIALS", use_container_width=True):
                if new_user and new_pass and new_totp:
                    # Update credentials.json
                    curr_creds['username'] = new_user
                    curr_creds['password'] = new_pass
                    curr_creds['totp_key'] = new_totp
                    
                    with open('credentials.json', 'w') as f:
                        json.dump(curr_creds, f, indent=4)
                    
                    st.success("Credentials updated successfully!")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("All fields are required.")

    st.divider()
    st.subheader("📂 Manual Login (Fallback)")
    st.info("Follow these steps if automated login fails:")
    st.markdown(f"1. Open the [Flattrade Auth URL]({AUTH_URL}) in your browser.")
    st.markdown("2. Log in and authorize the application.")
    st.markdown("3. Copy the `request_code` from the redirect URL (it looks like `?code=...`).")
    
    st.link_button("Open Flattrade Auth", AUTH_URL, use_container_width=True)
    
    with st.form("flattrade_login_form"):
        input_data = st.text_input("Enter request_code or full redirect URL")
        submit_flat = st.form_submit_button("GENERATE TOKEN (MANUAL)", use_container_width=True)
        
        if submit_flat:
            if not input_data:
                st.warning("Please enter the request_code or URL.")
            else:
                try:
                    # Use regex to extract code if input is a URL
                    code_match = re.search(r"[?&]code=([^&#]+)", input_data)
                    request_code = code_match.group(1) if code_match else input_data
                    
                    import hashlib
                    hash_value = hashlib.sha256((API_KEY + request_code + API_SECRET).encode()).hexdigest()
                    payload = {"api_key": API_KEY, "request_code": request_code, "api_secret": hash_value}

                    with st.spinner("Generating access token..."):
                        response = requests.post(TOKEN_URL, json=payload)
                    
                    if response.status_code == 200:
                        data = response.json()
                        if data.get("stat") == "Ok":
                            st.success("Access token generated successfully!")
                            token = data['token']
                            st.code(token, language="text")
                            
                            flat_auth = {"api_key": API_KEY, "token": token}
                            with open("flattrade_auth.json", "w") as f:
                                json.dump(flat_auth, f, indent=4)
                            st.info("Token saved to `flattrade_auth.json`")
                        else:
                            st.error(f"Error: {data.get('emsg', 'Unknown error')}")
                    else:
                        st.error(f"Failed to generate access token. HTTP Status: {response.status_code}")
                except Exception as e:
                    st.error(f"An error occurred: {e}")

elif menu == "📦 Order Portal": # Order Portal
    st.header("📦 Flattrade Auto-Order Hub")
    # ---------------- AUTOMATION ENGINE ----------------
    @st.fragment(run_every="1s")
    def automation_monitor():
        # 1. Strategy Logic & Data Refresh
        ltp = 0.0
        data_available = False
        
        try:
            DATA_FILE = "market_data.json"
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, "r") as f:
                    data = json.load(f)
                
                ltp = data.get("ltp", 0.0)
                strend_data = data.get("supertrend", [])
                
                # Fetch live indicators if available dynamically
                if "live_strend" in data and data["live_strend"] != 0.0:
                    strend_val = data["live_strend"]
                    strend_trend = data["live_trend"]
                else:
                    strend_val = strend_data[-1].get("value", 0.0) if strend_data else 0.0
                    strend_trend = strend_data[-1].get("trend", 0) if strend_data else 0
                    
                ema_data = data.get("ema", [])
                if "live_ema" in data and data["live_ema"] != 0.0:
                    ema_val = data["live_ema"]
                else:
                    ema_val = ema_data[-1].get("value", 0.0) if ema_data else 0.0
                    
                data_available = True
                
                # 2. Strategy Logic: EMA Crossover
                if st.session_state.auto_trading_active:
                    current_phase = st.session_state.trading_phase
                    tsym = st.session_state.get('trade_tsym')
                    qty = st.session_state.get('trade_qty', 0)
                    exch = st.session_state.get('trade_exch')
                    
                    if tsym and qty > 0 and exch:
                        current_trend = 1 if ltp > ema_val else -1

                        # STATE 1: WAIT FOR DIP (Price must go into Downtrend first)
                        if current_phase == 'WAIT_FOR_DIP':
                            if current_trend == -1:
                                st.session_state.trading_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] 📉 Price below EMA. Strategy ARMED for BUY.")
                                st.session_state.trading_phase = 'BUY'
                                st.rerun()
                        
                        # STATE 2: BUY (Armed, waiting for Uptrend)
                        elif current_phase == 'BUY' and current_trend == 1:
                            res = place_flattrade_order(tsym, qty, exch, 'B')
                            if res.get('stat') == 'Ok':
                                st.session_state.trading_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ AUTO BUY: {tsym} @ {ltp} (Crossed above EMA)")
                                st.session_state.trading_phase = 'SELL'
                                st.session_state.last_order_side = f"BUY @ {ltp}"
                                st.rerun()
                            else:
                                st.session_state.trading_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ BUY FAILED: {res.get('emsg')}")
                        
                        # STATE 3: SELL (Bought, waiting for Downtrend)
                        elif current_phase == 'SELL' and current_trend == -1:
                            res = place_flattrade_order(tsym, qty, exch, 'S')
                            if res.get('stat') == 'Ok':
                                st.session_state.trading_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ AUTO SELL: {tsym} @ {ltp} (Crossed below EMA)")
                                st.session_state.trading_phase = 'WAIT_FOR_DIP' # RESET to wait for next cycle
                                st.session_state.last_order_side = f"SELL @ {ltp}"
                                st.rerun()
                            else:
                                st.session_state.trading_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ SELL FAILED: {res.get('emsg')}")
                    else:
                        if not tsym: st.session_state.trading_logs.append(f"⚠️ Strategy warning: tsym missing.")
        except Exception as e:
            st.session_state.trading_logs.append(f"⚠️ Monitor Error: {e}")

        # 3. UI Display (Market Feed & Logs)
        col_m1, col_m2 = st.columns([1, 1])
        with col_m1:
            st.subheader("Live Market Feed")
            if data_available:
                st.metric("LTP", f"{ltp:.2f}", delta=f"{ltp-strend_val:.2f} (vs Supertrend)")
                st.write(f"**EMA (200):** {ema_val:.2f}")
                st.write(f"**Supertrend:** {strend_val:.2f} ({'🟢 UP' if strend_trend == 1 else '🔴 DOWN'})")
            else:
                st.info("Waiting for market data...")
        
        with col_m2:
            st.subheader("Activity Logs")
            log_container = st.container(height=300)
            with log_container:
                for log in reversed(st.session_state.trading_logs):
                    st.write(log)

    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Configuration")
        trade_tsym = st.text_input("Trading Symbol (tsym)", value=st.session_state.trade_tsym_input, key="trade_tsym_input_ui")
        st.session_state.trade_tsym_input = trade_tsym # PERSIST: Update the source value so it stays on tab switch
        st.session_state.trade_tsym = trade_tsym
        
        trade_num_lots = st.number_input("Number of Lots (n)", value=1, min_value=1, step=1, key="trade_num_lots_input_p")
        
        # Determine Lot Size automatically based on index
        default_lot = 65 
        if "BANKNIFTY" in trade_tsym: default_lot = 15
        elif "FINNIFTY" in trade_tsym: default_lot = 40
        elif "SENSEX" in trade_tsym: default_lot = 20
        
        trade_lot_size = st.number_input("Lot Size (m)", value=default_lot, min_value=1, step=1, key="trade_lot_size_input_p")
        
        total_qty = trade_num_lots * trade_lot_size
        st.write(f"**Total Quantity:** {total_qty}")
        st.session_state.trade_qty = total_qty
        
        exch_map = {"NSE": 1, "NFO": 2, "MCX": 5, "BSE": 3, "CDS": 13, "BFO": 4}
        exch_keys = list(exch_map.keys())
        
        # Determine Default Exchange based on tsym
        default_exch_idx = 1 # Default NFO
        if "SENSEX" in trade_tsym.upper() or "BANKEX" in trade_tsym.upper():
            default_exch_idx = exch_keys.index("BFO")
        elif "NIFTY" in trade_tsym.upper():
            default_exch_idx = exch_keys.index("NFO")
            
        trade_exch = st.selectbox("Exchange (exch)", options=exch_keys, index=default_exch_idx, key="trade_exch_input_p")
        st.session_state.trade_exch = trade_exch
        
        st.divider()
        
        # Strategy Monitor
        st.subheader("Strategy Monitor")
        m_c1, m_c2 = st.columns(2)
        with m_c1:
            st.write("**Next Action:**")
            if st.session_state.trading_phase == 'WAIT_FOR_DIP':
                color = "#58a6ff"
                label = "WAIT FOR DIP"
            elif st.session_state.trading_phase == 'BUY':
                color = "#26a69a"
                label = "BUY ON CROSS"
            else:
                color = "#ef5350"
                label = "SELL ON CROSS"
            st.markdown(f"<h3 style='color: {color}; margin:0;'>{label}</h3>", unsafe_allow_html=True)
        with m_c2:
            st.write("**Status:**")
            st.write("🟢 Active" if st.session_state.auto_trading_active else "🔴 Paused")

        st.divider()
        
        if not st.session_state.auto_trading_active:
            if st.button("🚀 START AUTO TRADING", type="primary", use_container_width=True):
                if not st.session_state.backend_running:
                    st.error("Backend System is Offline! Start it in the Dashboard first.")
                else:
                    st.session_state.auto_trading_active = True
                    st.session_state.trading_phase = 'WAIT_FOR_DIP' # INITIAL STATE
                    st.session_state.last_order_side = None
                    st.session_state.trading_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] 🤖 Strategy Activated. Waiting for Price to drop below EMA...")
                    st.rerun()
        else:
            if st.button("🛑 STOP AUTO TRADING", type="secondary", use_container_width=True):
                # AUTO CLOSE: If a BUY order was placed (phase is SELL), apply a SELL order before stopping
                if st.session_state.trading_phase == 'SELL':
                    tsym = st.session_state.get('trade_tsym')
                    qty = st.session_state.get('trade_qty', 0)
                    exch = st.session_state.get('trade_exch')
                    
                    if tsym and qty > 0 and exch:
                        st.session_state.trading_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 Stopping. Closing open position first...")
                        res = place_flattrade_order(tsym, qty, exch, 'S')
                        if res.get('stat') == 'Ok':
                            st.session_state.trading_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ AUTO SELL (STOP-CLOSE): {tsym} @ Market")
                        else:
                            st.session_state.trading_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ STOP-CLOSE FAILED: {res.get('emsg')}")
                
                st.session_state.auto_trading_active = False
                st.session_state.trading_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 Strategy Stopped.")
                st.rerun()

    with col2:
        # Combined Monitor Fragment Call
        automation_monitor()
        
        if st.button("🗑️ Clear Logs"):
            st.session_state.trading_logs = []
            st.session_state.last_order_side = None
            st.rerun()

elif menu == "📦 Scrip Master":
    st.header("📦 Scrip Master")
    
    # Live Indices Banner
    st.subheader("🌕 Live Market Indices")
    indices_banner_fragment()
    st.divider()
    
    SCRIP_MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
    
    @st.cache_data(ttl=86400) # Cache for 24 hours
    def fetch_scrip_master():
        LOCAL_SCRIP_CACHE = "scrip_master.json"
        
        # 1. Try Loading from Local Cache first (if fresh)
        if os.path.exists(LOCAL_SCRIP_CACHE):
            try:
                mtime = os.path.getmtime(LOCAL_SCRIP_CACHE)
                if time.time() - mtime < 86400: # 24 hours
                    with open(LOCAL_SCRIP_CACHE, "r") as f:
                        return json.load(f)
            except Exception as fe:
                print(f"Cache Load Error: {fe}")

        # 2. Fetch from URL
        try:
            with st.spinner("Downloading scrip master (~30MB)..."):
                response = requests.get(SCRIP_MASTER_URL, timeout=60)
                if response.status_code == 200:
                    data = response.json()
                    # Save to cache
                    try:
                        with open(LOCAL_SCRIP_CACHE, "w") as f:
                            json.dump(data, f)
                    except:
                        pass
                    return data
                else:
                    st.error(f"Scrip Master Fetch Failed: HTTP {response.status_code}")
                    return None
        except requests.exceptions.Timeout:
            st.error("Scrip Master Fetch Timeout (60s). Try refreshing or check internet.")
        except Exception as e:
            st.error(f"Scrip Master Request Error: {str(e)}")
        
        # 3. Fallback to old cache even if stale
        if os.path.exists(LOCAL_SCRIP_CACHE):
            try:
                with open(LOCAL_SCRIP_CACHE, "r") as f:
                    st.warning("Using stale scrip master data from cache.")
                    return json.load(f)
            except:
                pass
        return None

    def get_flattrade_tsym(token_data):
        try:
            name = token_data['name'].strip().upper()
            raw_exp = token_data['expiry'].strip().upper()
            dt = datetime.strptime(raw_exp, '%d%b%Y')
            
            strike_val = pd.to_numeric(token_data['strike'], errors='coerce') / 100
            strike = f"{strike_val:.0f}"
            
            exch = token_data['exch_seg']
            
            if exch in ['BFO', 'BSE']:
                # SENSEX BFO format: [NAME][YY][MMM][STRIKE][CE/PE]
                exp_fmt = dt.strftime('%y%b').upper()
                opt_type = 'CE' if token_data['symbol'].endswith('CE') else 'PE'
                return f"{name}{exp_fmt}{strike}{opt_type}"
            else:
                # NFO format: [NAME][DD][MMM][YY][C/P][STRIKE]
                exp_fmt = dt.strftime('%d%b%y').upper()
                opt_type = 'C' if token_data['symbol'].endswith('CE') else 'P'
                return f"{name}{exp_fmt}{opt_type}{strike}"
        except:
            return "N/A"

    def render_token_card(title, token_data, color):
        if token_data is not None:
            tsym = get_flattrade_tsym(token_data)
            st.markdown(f"""
            <div style="background-color: #161b22; border: 1px solid {color}; border-radius: 12px; padding: 20px; text-align: center;">
                <div style="color: #8b949e; font-size: 0.9rem; margin-bottom: 10px;">{title}</div>
                <div style="color: {color}; font-size: 1.8rem; font-weight: 800; margin-bottom: 5px;">{token_data['symbol']}</div>
                <div style="background-color: #0d1117; padding: 5px; border-radius: 4px; color: #58a6ff; font-family: monospace; font-size: 1.1rem; margin: 10px 0;">{tsym}</div>
                <div style="color: #8b949e; font-size: 1.2rem; font-weight: 600;">ID: {token_data['token']}</div>
                <div style="color: #8b949e; font-size: 0.8rem; margin-top: 10px;">Exchange: {token_data['exch_seg']}</div>
            </div>
            """, unsafe_allow_html=True)
            if st.button(f"📊 Track {token_data['symbol']}", key=f"track_{token_data['token']}", use_container_width=True):
                st.session_state.dashboard_token = str(token_data['token'])
                st.session_state.dashboard_exchange = token_data['exch_seg']
                # Sync with Order Portal
                st.session_state.trade_tsym_input = tsym
                st.session_state.trade_tsym = tsym
                st.toast(f"🚀 {token_data['symbol']} loaded into Dashboard & Order Portal!")
        else:
            st.info(f"No {title} data found")

    raw_data = fetch_scrip_master()
    if not raw_data:
        st.error("Failed to load scrip master.")
    else:
        df = pd.DataFrame(raw_data)
        
        # UI Selection Flow
        st.subheader("Tiered Selection")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            instr_options = ["NIFTY", "SENSEX"]
            new_instr = st.selectbox("Select Index", options=instr_options)
            if new_instr != st.session_state.selected_instrument:
                st.session_state.selected_instrument = new_instr
                st.session_state.selected_expiry = None
                st.session_state.selected_strike = None
                st.rerun()

        # Filtering for Expiries
        filtered_df = df[df['name'] == st.session_state.selected_instrument]
        if st.session_state.selected_instrument == 'SENSEX':
            filtered_df = filtered_df[filtered_df['exch_seg'].isin(['BFO', 'BSE'])]
        else:
            filtered_df = filtered_df[filtered_df['exch_seg'] == 'NFO']
            
        exp_list = sorted(
            [e for e in list(set(filtered_df['expiry'].dropna().str.strip().str.upper())) if e],
            key=lambda x: datetime.strptime(x, '%d%b%Y')
        )
        
        with col2:
            new_exp = st.selectbox("Select Expiry", options=[None] + exp_list, index=0 if not st.session_state.selected_expiry else exp_list.index(st.session_state.selected_expiry)+1)
            if new_exp != st.session_state.selected_expiry:
                st.session_state.selected_expiry = new_exp
                st.session_state.selected_strike = None
                st.rerun()

        if st.session_state.selected_expiry:
            exp_df = filtered_df[filtered_df['expiry'].str.strip().str.upper() == st.session_state.selected_expiry]
            strike_list = sorted(list(set(pd.to_numeric(exp_df['strike'], errors='coerce') / 100)))
            strike_list = [f"{s:.0f}" for s in strike_list]
            
            with col3:
                new_strike = st.selectbox("Select Strike", options=[None] + strike_list, index=0 if not st.session_state.selected_strike else strike_list.index(st.session_state.selected_strike)+1)
                if new_strike != st.session_state.selected_strike:
                    st.session_state.selected_strike = new_strike
                    st.rerun()

        if st.session_state.selected_strike:
            st.divider()
            strike_float = float(st.session_state.selected_strike) * 100
            final_df = exp_df[pd.to_numeric(exp_df['strike'], errors='coerce') == strike_float]
            
            ce_token = final_df[final_df['symbol'].str.endswith('CE', na=False)].to_dict('records')
            pe_token = final_df[final_df['symbol'].str.endswith('PE', na=False)].to_dict('records')
            
            c1, c2 = st.columns(2)
            with c1: render_token_card("CALL OPTION", ce_token[0] if ce_token else None, "#26a69a")
            with c2: render_token_card("PUT OPTION", pe_token[0] if pe_token else None, "#ef5350")
            
            if st.button("Clear Selection"):
                st.session_state.selected_expiry = None
                st.session_state.selected_strike = None
                st.rerun()
