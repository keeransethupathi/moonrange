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
import streamlit.components.v1 as components
import psutil
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


def kill_process_by_pid(pid_file):
    """Attempt to kill a process given its PID file."""
    if os.path.exists(pid_file):
        try:
            with open(pid_file, "r") as f:
                pid = int(f.read().strip())
            if psutil.pid_exists(pid):
                proc = psutil.Process(pid)
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except psutil.TimeoutExpired:
                    proc.kill()
            os.remove(pid_file)
            return True
        except Exception as e:
            print(f"Error killing process {pid_file}: {e}")
    return False





def launch_angelone_backend(exch, token, range_val, force=True):
    """Launch the original AngelOne backend.py"""
    try:
        if not os.path.exists("auth.json"):
            return False, "AngelOne login required."
            
        cmd = [sys.executable, "backend.py", str(exch), str(token), str(range_val)]
        if sys.platform == "win32":
            subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen(cmd, start_new_session=True)
        return True, "AngelOne Backend Launching..."
    except Exception as e:
        return False, f"Launch error: {e}"


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
    """Launch the background indices collector."""
    try:
        if force or not os.path.exists("flattrade_indices.pid"):
            cmd = [sys.executable, "flattrade_indices.py"]
            if sys.platform == "win32":
                subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE)
            else:
                subprocess.Popen(cmd, start_new_session=True)
            return True, "Indices Backend Launching..."
        return False, "Indices Backend Already Running."
    except Exception as e:
        return False, f"Launch error: {e}"


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
    
    col1.metric("Price", f"₹{ltp:,.2f}", delta=f"{ltp-latest_ema:,.2f} vs EMA")
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
    st.session_state.dashboard_token = "486503"
if 'dashboard_exchange' not in st.session_state:
    st.session_state.dashboard_exchange = "MCX"
if 'trade_tsym_input' not in st.session_state:
    st.session_state.trade_tsym_input = "NIFTY24FEB26C26000"
if 'trade_exch_input' not in st.session_state:
    st.session_state.trade_exch_input = "NFO"
if 'dashboard_range' not in st.session_state:
    st.session_state.dashboard_range = 0.05
if 'resolver_code' not in st.session_state:
    st.session_state.resolver_code = ""

# ================= GLOBAL AUTOMATION ENGINE =================
@st.fragment(run_every="1s")
def headless_automation_engine():
    if not st.session_state.get('auto_trading_active', False):
        return
        
    try:
        from order import place_flattrade_order
        DATA_FILE = "market_data.json"
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r") as f:
                data = json.load(f)
            
            ltp = data.get("ltp", 0.0)
            ema_data = data.get("ema", [])
            ema_val = data.get("live_ema", ema_data[-1].get("value", 0.0) if ema_data else 0.0)
            
            current_phase = st.session_state.trading_phase
            tsym = st.session_state.get('trade_tsym')
            qty = st.session_state.get('trade_qty', 0)
            exch = st.session_state.get('trade_exch')
            
            if tsym and qty > 0 and exch and ltp > 0 and ema_val > 0:
                current_trend = 1 if ltp > ema_val else -1
                
                # Recover from any newly corrupted states
                if current_phase not in ['WAIT_FOR_DIP', 'BUY', 'SELL']:
                    current_phase = 'WAIT_FOR_DIP'
                    st.session_state.trading_phase = 'WAIT_FOR_DIP'

                if current_phase == 'WAIT_FOR_DIP':
                    if current_trend == -1:
                        st.session_state.trading_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] 📉 Price below EMA. Strategy ARMED for BUY.")
                        st.session_state.trading_phase = 'BUY'
                
                elif current_phase == 'BUY' and current_trend == 1:
                    res = place_flattrade_order(tsym, qty, exch, 'B')
                    if res.get('stat') == 'Ok':
                        st.session_state.trading_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ AUTO BUY: {tsym} @ Limit Price. (Crossed above EMA)")
                        st.session_state.trading_phase = 'SELL'
                        st.session_state.last_order_side = f"BUY @ {ltp}"
                    else:
                        st.session_state.trading_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ BUY FAILED: {res.get('emsg')}")
                        st.session_state.trading_phase = 'WAIT_FOR_DIP'
                        st.session_state.auto_trading_active = False 
                        
                elif current_phase == 'SELL' and current_trend == -1:
                    res = place_flattrade_order(tsym, qty, exch, 'S')
                    if res.get('stat') == 'Ok':
                        st.session_state.trading_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ AUTO SELL: {tsym} @ Limit Price. (Crossed below EMA)")
                        st.session_state.trading_phase = 'WAIT_FOR_DIP'
                        st.session_state.last_order_side = f"SELL @ {ltp}"
                    else:
                        st.session_state.trading_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ SELL FAILED: {res.get('emsg')}")
                        st.session_state.trading_phase = 'WAIT_FOR_DIP'
                        st.session_state.auto_trading_active = False 
    except Exception as e:
        # Don't silently fail; push to the logs so the user sees it
        st.session_state.trading_logs.append(f"⚠️ Global Engine Error {str(e)}")
        pass

    # Ensures Streamlit frontend registers the fragment for polling
    st.empty()

headless_automation_engine()




# Silence ScriptRunContext and other warnings
logging.getLogger("streamlit.runtime.scriptrunner").setLevel(logging.ERROR)
logging.getLogger("smartWebSocketV2").setLevel(logging.ERROR)

# ================= UI =================
st.title("🛡️ AngelOne Intelligence Hub")

# Sidebar Menu for Navigation
with st.sidebar:
    st.header(" NAVIGATION")
    menu = st.radio("Go to", ["📊 Dashboard", "🔐 Login Portal", "📦 Order Portal", "📦 Scrip Master"])


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
            if st.button("🚀 Start AngelOne Backend", type="primary", use_container_width=True):
                # AngelOne Backend
                if not os.path.exists("auth.json"):
                    st.error("AngelOne login required. Go to 'Login Portal'.")
                else:
                    success, msg = launch_angelone_backend(exchange_type, token_id, range_val)
                    if success:
                        st.success(msg)
                        st.session_state.backend_running = True
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(msg)
        else:
            if st.button("🛑 Stop Backend", use_container_width=True):

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
        
        if st.button("🗑️ Reset Data", use_container_width=True):
            with st.status("Resetting system... please wait.") as status:
                st.write("🛑 Stopping backend processes...")
                # 1. Stop Signal
                with open(STOP_FILE, "w") as f:
                    f.write("stop")
                
                # 2. Hard kill if they don't stop gracefully
                time.sleep(1)
                kill_process_by_pid("backend_angelone.pid")
                kill_process_by_pid("flattrade_indices.pid")
                
                st.write("🧹 Clearing data files...")
                # 3. Clear Persistent Data
                targets = ["market_data.json", "market_data.db", "flattrade_indices.json", "backend_debug.log"]
                for f_path in targets:
                    if os.path.exists(f_path):
                        for _ in range(3):
                            try:
                                os.remove(f_path)
                                break
                            except:
                                time.sleep(0.5)
                
                # 4. Clear screenshot logs
                if os.path.exists("logs"):
                    for f in os.listdir("logs"):
                        if f.endswith(".png"):
                            try: os.remove(os.path.join("logs", f))
                            except: pass

                # 5. Clear State
                st.session_state.ohlc_data = []
                st.session_state.ema_data = []
                st.session_state.supertrend_data = []
                st.session_state.live_ema = 0.0
                st.session_state.live_strend = 0.0
                st.session_state.current_ltp = 0.0
                st.session_state.trading_logs = []
                st.session_state.last_error = None
                st.session_state.backend_running = False
                
                status.update(label="System Reset Complete!", state="complete")
                time.sleep(1)
                st.rerun()


    # Call Fragment for Live Updates
    display_dashboard_fragment(token_id, exchange_type, exchange_mapping)

elif menu == "🔐 Login Portal": # Login Portal
    # Diagnostic: Show IP to verify IPv4 enforcement
    try:
        from auto_login import get_outbound_ip
        current_ip = get_outbound_ip()
        st.info(f"🌐 **Current Outbound IP:** `{current_ip}`")
        st.caption("Ensure this IP is whitelisted in your Flattrade API Portal.")
    except:
        pass
        
    st.header("🔐 AngelOne Login")
    
    existing_auth = {}
    if os.path.exists("auth.json"):
        with open("auth.json", "r") as f:
            existing_auth = json.load(f)

    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        with st.form("login_form"):
            default_c_code = safe_get_secret("ANGEL_CLIENT_CODE", existing_auth.get("client_code", "K135836"))
            # Use previously provided API key as default
            default_api_k = safe_get_secret("ANGEL_API_KEY", existing_auth.get("api_key", "t0bsCNdW"))
            default_totp_s = safe_get_secret("ANGEL_TOTP_SECRET", existing_auth.get("totp_secret", "YGDC6I7VDV7KJSIELCN626FKBY"))

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

    st.divider()
    st.header("📈 Flattrade Login")
    
    API_KEY = safe_get_secret("FT_API_KEY", "b5768d873c474155a3d09d56a50f5314")
    API_SECRET = safe_get_secret("FT_API_SECRET", "2025.3bb14ae6afd04844b10e338a6f388a9c7416205cb6990c69")
    AUTH_URL = f"https://auth.flattrade.in/?app_key={API_KEY}"
    TOKEN_URL = "https://authapi.flattrade.in/trade/apitoken"

    # Automated Login Section
    st.subheader("🤖 Automated Login")
    
    is_cloud = "STREAMLIT_RUNTIME_ENV" in os.environ or os.environ.get("HOSTNAME") == "streamlit"
    if is_cloud:
        st.error("⚠️ **Cloud Restriction**: Flattrade blocks automated login from data-center IPs. Use the **Universal Cloud Connector** below instead.")
    else:
        st.info("Click the button below to automatically login and generate your access token.")
    
    if st.button("🚀 Run Auto Login", type="secondary" if is_cloud else "primary", use_container_width=True):
        try:
            from auto_login import auto_login, generate_access_token
            with st.status("Running automated login...") as status:
                log_placeholder = st.empty()
                logs = []
                def ui_logger(msg):
                    logs.append(msg)
                    with log_placeholder.container():
                        for m in logs[-5:]: st.write(f"› {m}")

                login_creds = {
                    'username': safe_get_secret('FT_USERNAME'),
                    'password': safe_get_secret('FT_PASSWORD'),
                    'totp_key': safe_get_secret('FT_TOTP_KEY'),
                    'api_key': API_KEY, 'api_secret': API_SECRET
                }
                result = auto_login(creds=login_creds, headless=True, log_func=ui_logger)
                if result["status"] == "success":
                    request_code = result["code"]
                    st.session_state.resolver_code = request_code # Handover for resolver
                    token = result.get("token")
                    if not token:
                        res = generate_access_token(request_code, api_key=API_KEY, api_secret=API_SECRET)
                        token = res.get("token") if res["status"] == "success" else None
                    
                    if token:
                        st.success("Access token generated successfully!")
                        flat_auth = {"api_key": API_KEY, "token": token}
                        with open("flattrade_auth.json", "w") as f:
                            json.dump(flat_auth, f, indent=4)
                        status.update(label="Login Successful!", state="complete")
                    else:
                        st.session_state.last_error = "INVALID_IP"
                        st.error("Token Generation Blocked (INVALID_IP). Use the 'Cloud Token Resolver' below.")
                        status.update(label="Token Generation Failed (Cloud Blocked)", state="error")
                else:
                    st.error(f"Automation failed: {result.get('message')}")
                    status.update(label="Automation Failed", state="error")
        except Exception as e:
            st.error(f"Error: {e}")

    # --- CLOUD TOKEN RESOLVER (IP BYPASS) ---
    resolver_expanded = bool(st.session_state.resolver_code)
    with st.expander("🌐 Cloud Token Resolver (Bypass INVALID_IP)", expanded=resolver_expanded):
        if resolver_expanded:
            st.warning("⚠️ **Cloud Block Detected**: The request code has been captured. Click RESOLVE below to finish login using your Resident IP.")
        else:
            st.info("Paste your request_code below to exchange it using your Resident IP.")
        
        resolver_code = st.text_input("Captured Code", value=st.session_state.resolver_code, key="resolver_input")
        st.session_state.resolver_code = resolver_code
        
        import hashlib
        res_hash = hashlib.sha256((API_KEY + resolver_code + API_SECRET).encode()).hexdigest() if resolver_code else ""
        
        # JS Fetch Component
        components.html(f"""
            <div style="background:#0d1117; padding:12px; border-radius:8px; border:1px solid #30363d; font-family:sans-serif; color:white;">
                <button id="resBtn" style="width:100%; padding:10px; background:#238636; color:white; border:none; border-radius:6px; cursor:pointer; font-weight:600; margin-bottom:10px;">
                    🔓 RESOLVE TOKEN (Local IP)
                </button>
                <div id="resStat" style="font-size:0.85rem; color:#8b949e; word-break:break-all;">Ready...</div>
            </div>
            <script>
                const btn = document.getElementById('resBtn');
                const stat = document.getElementById('resStat');
                btn.onclick = async () => {{
                    const code = "{resolver_code}";
                    if(!code) {{ stat.innerText = "❌ Paste Code First!"; return; }}
                    stat.innerText = "⏳ Exchanging via Resident IP...";
                    try {{
                        const res = await fetch("https://authapi.flattrade.in/trade/apitoken", {{
                            method: "POST",
                            headers: {{ "Content-Type": "application/json" }},
                            body: JSON.stringify({{ api_key: "{API_KEY}", request_code: code, api_secret: "{res_hash}" }})
                        }});
                        const data = await res.json();
                        if(data.stat === "Ok") {{
                            stat.innerHTML = "✅ <b>SUCCESS!</b><br>Copy this token:<br><code style='color:#58a6ff'>" + data.token + "</code>";
                        }} else {{
                            stat.innerText = "❌ API Error: " + (data.emsg || "Unknown");
                        }}
                    }} catch(e) {{
                        stat.innerText = "❌ Connection Blocked/Failed.";
                    }}
                }};
            </script>
        """, height=150)
        
        st.caption("Copy the generated token above and paste it into 'Fallback' below to save.")



    st.divider()
    st.subheader("📂 Manual Login (Fallback)")
    st.link_button("Open Flattrade Auth", AUTH_URL, use_container_width=True)
    with st.form("flattrade_login_form"):
        input_data = st.text_input("Enter request_code or full redirect URL")
        submit_flat = st.form_submit_button("GENERATE TOKEN (MANUAL)", use_container_width=True)
        if submit_flat:
            try:
                code_match = re.search(r"[?&]code=([^&#]+)", input_data)
                request_code = code_match.group(1) if code_match else input_data
                import hashlib
                hash_value = hashlib.sha256((API_KEY + request_code + API_SECRET).encode()).hexdigest()
                payload = {"api_key": API_KEY, "request_code": request_code, "api_secret": hash_value}
                response = requests.post(TOKEN_URL, json=payload)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("stat") == "Ok":
                        st.success("Access token generated successfully!")
                        flat_auth = {"api_key": API_KEY, "token": data['token']}
                        with open("flattrade_auth.json", "w") as f:
                            json.dump(flat_auth, f, indent=4)
                    else: st.error(data.get('emsg'))
                else: st.error(f"HTTP {response.status_code}")
            except Exception as e: st.error(f"Error: {e}")












elif menu == "📦 Order Portal": # Order Portal
    st.header("📦 Flattrade Auto-Order Hub")
    
    @st.fragment(run_every="1s")
    def automation_monitor_ui():
        ltp = st.session_state.get('current_ltp', 0.0)
        ema_val = st.session_state.get('live_ema', 0.0)
        logs = st.session_state.get('trading_logs', [])
        
        col_m1, col_m2 = st.columns([1, 1])
        with col_m1:
            st.subheader("Live Market Feed")
            st.metric("LTP", f"₹{ltp:.2f}", delta=f"{ltp-ema_val:.2f} (vs EMA)")
            st.write(f"**EMA (200):** {ema_val:.2f}")
        with col_m2:
            st.subheader("Activity Logs")
            log_container = st.container(height=300)
            with log_container:
                for log in reversed(logs):
                    st.write(log)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Configuration")
        trade_tsym = st.text_input("Trading Symbol (tsym)", value=st.session_state.get('trade_tsym_input', ''))
        st.session_state.trade_tsym_input = trade_tsym
        st.session_state.trade_tsym = trade_tsym
        
        qty = st.number_input("Total Quantity", value=st.session_state.get('trade_qty', 1), min_value=1)
        st.session_state.trade_qty = qty
        
        trade_exch = st.selectbox("Exchange", options=["NFO", "BFO", "NSE", "BSE"], index=0)
        st.session_state.trade_exch = trade_exch
        
        st.divider()
        if not st.session_state.get('auto_trading_active', False):
            if st.button("🚀 START AUTO TRADING", type="primary", use_container_width=True):
                st.session_state.auto_trading_active = True
                st.session_state.trading_phase = 'WAIT_FOR_DIP'
                st.session_state.trading_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] 🤖 Strategy Activated.")
                st.rerun()
        else:
            if st.button("🛑 STOP AUTO TRADING", use_container_width=True):
                st.session_state.auto_trading_active = False
                st.session_state.trading_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 Strategy Stopped.")
                st.rerun()

    with col2:
        automation_monitor_ui()

elif menu == "📦 Scrip Master":
    st.header("📦 Scrip Master")
    
    # Balance Fragment
    @st.fragment
    def flattrade_balance_fragment():
        if st.button("💰 Show Flattrade Balance", use_container_width=True):
            with st.spinner("Fetching Balance..."):
                try:
                    with open('flattrade_auth.json', 'r') as f:
                        token = json.load(f).get('token')
                    uid = os.environ.get('FT_USERNAME', "K135836")
                    if token and uid:
                        url = "https://piconnect.flattrade.in/PiConnectAPI/Limits"
                        payload = 'jData=' + json.dumps({"uid": uid, "actid": uid}) + '&jKey=' + token
                        res = requests.post(url, data=payload).json()
                        if res.get('stat') == 'Ok':
                            total = float(res.get('cash', 0.0)) + float(res.get('payin', 0.0)) - float(res.get('marginused', 0.0))
                            st.success(f"**Available Training Margin:** ₹{total:,.2f}")
                        else: st.error(res.get('emsg'))
                    else: st.warning("Login first.")
                except Exception as e: st.error(str(e))
                    
    flattrade_balance_fragment()
    st.divider()

    # Live Indices Banner
    st.subheader("🌙 Live Market Indices")
    indices_banner_fragment()
    st.divider()
    
    SCRIP_MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
    
    @st.cache_data(ttl=86400) # Cache for 24 hours
    def fetch_scrip_master():
        LOCAL_SCRIP_CACHE = "scrip_master.json"
        if os.path.exists(LOCAL_SCRIP_CACHE):
            try:
                if time.time() - os.path.getmtime(LOCAL_SCRIP_CACHE) < 86400:
                    with open(LOCAL_SCRIP_CACHE, "r") as f: return json.load(f)
            except: pass

        try:
            with st.spinner("Downloading scrip master (~30MB)..."):
                response = requests.get(SCRIP_MASTER_URL, timeout=60)
                if response.status_code == 200:
                    data = response.json()
                    with open(LOCAL_SCRIP_CACHE, "w") as f: json.dump(data, f)
                    return data
        except: pass
        return None

    def get_flattrade_tsym(token_data):
        try:
            name = token_data['name'].strip().upper()
            dt = datetime.strptime(token_data['expiry'].strip().upper(), '%d%b%Y')
            strike = f"{pd.to_numeric(token_data['strike'], errors='coerce') / 100:.0f}"
            if token_data['exch_seg'] in ['BFO', 'BSE']:
                return f"{name}{dt.strftime('%y%b').upper()}{strike}{'CE' if token_data['symbol'].endswith('CE') else 'PE'}"
            return f"{name}{dt.strftime('%d%b%y').upper()}{'C' if token_data['symbol'].endswith('CE') else 'P'}{strike}"
        except: return "N/A"

    def render_token_card(title, token_data, color):
        if token_data:
            tsym = get_flattrade_tsym(token_data)
            st.markdown(f"""
            <div style="background-color: #161b22; border: 1px solid {color}; border-radius: 12px; padding: 20px; text-align: center;">
                <div style="color: #8b949e; font-size: 0.9rem; margin-bottom: 10px;">{title}</div>
                <div style="color: {color}; font-size: 1.8rem; font-weight: 800; margin-bottom: 5px;">{token_data['symbol']}</div>
                <div style="background-color: #0d1117; padding: 5px; border-radius: 4px; color: #58a6ff; font-family: monospace; font-size: 1.1rem; margin: 10px 0;">{tsym}</div>
                <div style="color: #8b949e; font-size: 1.2rem; font-weight: 600;">ID: {token_data['token']}</div>
            </div>
            """, unsafe_allow_html=True)
            if st.button(f"📊 Track {token_data['symbol']}", key=f"track_{token_data['token']}", use_container_width=True):
                st.session_state.dashboard_token = str(token_data['token'])
                st.session_state.dashboard_exchange = token_data['exch_seg']
                st.session_state.trade_tsym_input = tsym
                st.session_state.trade_tsym = tsym
                st.toast(f"🚀 {token_data['symbol']} loaded!")
        else: st.info(f"No {title} data found")

    raw_data = fetch_scrip_master()
    if raw_data:
        df = pd.DataFrame(raw_data)
        st.subheader("Tiered Selection")
        col1, col2, col3 = st.columns(3)
        with col1:
            instr = st.selectbox("Select Index", options=["NIFTY", "SENSEX"])
        filtered_df = df[df['name'] == instr]
        filtered_df = filtered_df[filtered_df['exch_seg'].isin(['BFO', 'BSE'])] if instr == 'SENSEX' else filtered_df[filtered_df['exch_seg'] == 'NFO']
        exp_list = sorted([x for x in set(filtered_df['expiry'].dropna().str.strip().str.upper()) if x], key=lambda x: datetime.strptime(x, '%d%b%Y'))
        with col2:
            exp = st.selectbox("Select Expiry", options=[None] + exp_list)
        if exp:
            exp_df = filtered_df[filtered_df['expiry'].str.strip().str.upper() == exp]
            strike_list = sorted([f"{s:.0f}" for s in set(pd.to_numeric(exp_df['strike'], errors='coerce') / 100)])
            with col3:
                strike = st.selectbox("Select Strike", options=[None] + strike_list)
            if strike:
                st.divider()
                s_float = float(strike) * 100
                final_df = exp_df[pd.to_numeric(exp_df['strike'], errors='coerce') == s_float]
                ce = final_df[final_df['symbol'].str.endswith('CE')].to_dict('records')
                pe = final_df[final_df['symbol'].str.endswith('PE')].to_dict('records')
                c1, c2 = st.columns(2)
                with c1: render_token_card("CALL OPTION", ce[0] if ce else None, "#26a69a")
                with c2: render_token_card("PUT OPTION", pe[0] if pe else None, "#ef5350")


