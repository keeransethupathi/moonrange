import streamlit as st
import json
import pandas as pd
import numpy as np
import time
import os
import requests
import pyotp
import sys
from datetime import datetime
from custom_tv_chart import renderCustomLightweightCharts
from order import place_flattrade_order

# ================= STREAMLIT CONFIG (FIXED VIEWPORT) =================
st.set_page_config(layout="wide", page_title="Control Tower Terminal", initial_sidebar_state="expanded")

STOP_FILE = "stop_indices.txt"
DATA_FILE = "market_data.json"

def safe_get_secret(key, default=None):
    try:
        if key in st.secrets: return st.secrets[key]
    except: pass
    return os.environ.get(key, default)

def sync_market_data():
    data_found = False
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r") as f: data = json.load(f)
            last_update = data.get("last_update", 0)
            if time.time() - last_update < 10:
                st.session_state.backend_running = True
                IST_OFFSET = 19800 
                st.session_state.ohlc_data = [{**b, "time": b["time"] + IST_OFFSET} for b in data.get("ohlc", [])]
                st.session_state.ema_data = [{**b, "time": b["time"] + IST_OFFSET} for b in data.get("ema", [])]
                st_data_raw = data.get("supertrend", [])
                st_formatted = [{"time": b["time"] + IST_OFFSET, "value": b["value"], "color": ('#4caf50' if b.get('trend', 1) == 1 else '#f44336')} for b in st_data_raw]
                st.session_state.supertrend_data = st_formatted
                st.session_state.current_ltp = float(data.get("ltp", 0.0))
                st.session_state.live_ema = float(data.get("live_ema", 0.0))
                st.session_state.live_strend = float(data.get("live_strend", 0.0))
                data_found = True
            else: st.session_state.backend_running = False
    except: pass
    return data_found

def get_indices_snapshot():
    file_path = "flattrade_indices.json"
    if os.path.exists(file_path):
        try:
            with open(file_path, "r") as f:
                data = json.load(f)
                if time.time() - data.get("last_update", 0) < 60: return data.get("prices", {})
        except: pass
    return {"NIFTY 50": {"lp": "0.0", "pc": "0.0"}, "SENSEX": {"lp": "0.0", "pc": "0.0"}}

# ================= UI Styling (AGGRESSIVE ZERO SCROLL) =================
st.markdown("""
<style>
    /* Balanced Viewport Lock */
    html, body, [data-testid="stAppViewContainer"] {
        overflow: hidden !important;
        height: 100vh !important;
    }
    .main .block-container {
        padding-top: 0rem !important;
        margin-top: -3.5rem !important;
        padding-bottom: 0rem !important;
        max-width: 98% !important;
        height: 100vh;
        overflow: hidden !important;
    }
    [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"] { display: none !important; }
    
    /* Standardized Gap Control */
    [data-testid="stVerticalBlock"] { gap: 0.75rem !important; }
    [data-testid="stVerticalBlock"] > div { padding-bottom: 0px !important; margin-bottom: 0px !important; }
    .stHorizontalBlock { gap: 0.8rem !important; }
    
    /* Widget Spacing */
    .stSelectbox, .stTextInput, .stNumberInput { margin-bottom: 2px !important; }
    .stButton>button { width: 100% !important; height: 1.8rem !important; font-size: 0.7rem !important; padding: 0px !important; }
    
    /* Compactor Metric Layout - Smaller for Space */
    .stMetric { 
        background-color: #0d1117 !important; 
        border: 1px solid #30363d !important; 
        border-radius: 4px !important; 
        padding: 4px 8px !important;
    }
    [data-testid="stMetricValue"] { color: #58a6ff !important; font-weight: 700 !important; font-size: 0.85rem !important; }
    [data-testid="stMetricLabel"] { color: #8b949e !important; font-size: 0.55rem !important; text-transform: uppercase; }
    
    /* Sidebar Polishing */
    .sidebar .sidebar-content { padding: 1rem !important; }
    [data-testid="stSidebar"] { border-right: 1px solid #30363d !important; background-color: #0d1117 !important; }
    
    /* Internal Scrolling Gaps */
    .element-container { margin-bottom: 2px !important; }
    
    /* Kill all scrollbars */
    * { -ms-overflow-style: none !important; scrollbar-width: none !important; }
    *::-webkit-scrollbar { display: none !important; }
</style>
""", unsafe_allow_html=True)

# ================= STATE MANAGEMENT =================
state_defaults = {
    'ohlc_data': [], 'ema_data': [], 'supertrend_data': [],
    'live_ema': 0.0, 'live_strend': 0.0, 'current_ltp': 0.0, 'current_balance': 0.0,
    'dashboard_token': "486503", 'dashboard_exchange': "MCX", 'range_1r': 10.0,
    'auto_trading_active': False, 'trading_logs': [],
    'trade_tsym': "NIFTY24FEB26C26000", 'trade_qty': 65
}
for key, default in state_defaults.items():
    if key not in st.session_state: st.session_state[key] = default

# ================= SIDEBAR (LEFT CONTROL PANEL) =================
RAW_SCRIP_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"

@st.cache_data(ttl=86400)
def fetch_scrip_master():
    LOCAL_CSV = "scrip_master.json"
    if os.path.exists(LOCAL_CSV):
        try:
            with open(LOCAL_CSV, "r") as f: return json.load(f)
        except: pass
    try:
        r = requests.get(RAW_SCRIP_URL, timeout=30)
        if r.status_code == 200:
            with open(LOCAL_CSV, "w") as f: json.dump(r.json(), f)
            return r.json()
    except: pass
    return None

with st.sidebar:
    st.markdown("<div style='color:#58a6ff; font-weight:800; font-size:0.75rem; margin-bottom:10px;'>📦 ASSET SELECTION</div>", unsafe_allow_html=True)
    raw_data = fetch_scrip_master()
    if raw_data:
        df = pd.DataFrame(raw_data)
        instr = st.selectbox("Index", options=["NIFTY", "SENSEX"], key="sm_index", label_visibility="collapsed")
        f_df = df[df['name'] == instr]
        f_df = f_df[f_df['exch_seg'].isin(['BFO', 'BSE'])] if instr == 'SENSEX' else f_df[f_df['exch_seg'] == 'NFO']
        exp_list = sorted([x for x in set(f_df['expiry'].dropna().str.strip().str.upper()) if x], key=lambda x: datetime.strptime(x, '%d%b%Y'))
        exp = st.selectbox("Expiry", options=[None] + exp_list, key="sm_exp", label_visibility="collapsed")
        if exp:
            exp_df = f_df[f_df['expiry'].str.strip().str.upper() == exp]
            strike_list = sorted([f"{s:.0f}" for s in set(pd.to_numeric(exp_df['strike'], errors='coerce') / 100)])
            strike = st.selectbox("Strike", options=[None] + strike_list, key="sm_strike", label_visibility="collapsed")
            if strike:
                s_val = float(strike) * 100
                final_df = exp_df[pd.to_numeric(exp_df['strike'], errors='coerce') == s_val]
                tc1, tc2 = st.columns(2)
                for i, side in enumerate(["CE", "PE"]):
                    opt = final_df[final_df['symbol'].str.endswith(side)].to_dict('records')
                    if opt:
                        if [tc1, tc2][i].button(f"TRACK {side}", use_container_width=True):
                            st.session_state.dashboard_token = str(opt[0]['token'])
                            st.session_state.dashboard_exchange = opt[0]['exch_seg']
                            st.rerun()

    st.divider()
    st.markdown("<div style='color:#58a6ff; font-weight:800; font-size:0.75rem; margin-bottom:10px;'>⚡ SYSTEM CONTROL</div>", unsafe_allow_html=True)
    e1, e2 = st.columns([1, 1.2])
    st.session_state.dashboard_exchange = e1.selectbox("Exch", ["NFO", "MCX", "CDS", "BFO", "NSE", "BSE"], index=["NFO", "MCX", "CDS", "BFO", "NSE", "BSE"].index(st.session_state.dashboard_exchange), label_visibility="collapsed")
    st.session_state.dashboard_token = e2.text_input("TID", value=st.session_state.dashboard_token, label_visibility="collapsed")
    st.session_state.range_1r = st.number_input("Range 1R", value=st.session_state.range_1r, step=0.5)
    
    st.divider()
    st.markdown("<div style='color:#58a6ff; font-weight:800; font-size:0.75rem; margin-bottom:10px;'>🚀 CONNECTIVITY</div>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    if c1.button("🔑 ANGEL", use_container_width=True):
        from auto_login import angel_one_login
        with st.spinner("..."):
            success, msg = angel_one_login()
            if success: st.toast("Angel Connected")
            
    if c2.button("🔗 FLAT", use_container_width=True):
        from auto_login import auto_login, generate_access_token
        with st.spinner("..."):
            res = auto_login(headless=True)
            if res.get("status") == "success":
                token_res = generate_access_token(res["code"])
                if token_res["status"] == "success":
                    with open('flattrade_auth.json', 'w') as f: json.dump({"token": token_res["token"]}, f)
                    st.toast("FT Authorized")
    
    if st.button("💰 REFRESH BALANCE", use_container_width=True):
        try:
            with open('flattrade_auth.json', 'r') as f: token = json.load(f).get('token')
            uid = safe_get_secret("FT_USERNAME", "K135836")
            url = "https://piconnect.flattrade.in/PiConnectAPI/Limits"
            payload = 'jData=' + json.dumps({"uid": uid, "actid": uid}) + '&jKey=' + token
            res = requests.post(url, data=payload).json()
            if res.get('stat') == 'Ok':
                st.session_state.current_balance = float(res.get('cash', 0)) + float(res.get('payin', 0)) - float(res.get('marginused', 0))
                st.toast("Balance Updated")
        except: pass

    btn_label = "🛑 STOP" if st.session_state.auto_trading_active else "🚀 START"
    btn_type = "secondary" if st.session_state.auto_trading_active else "primary"
    if st.button(btn_label, type=btn_type, use_container_width=True):
        st.session_state.auto_trading_active = not st.session_state.auto_trading_active
        st.session_state.trading_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {'Started' if st.session_state.auto_trading_active else 'Stopped'}")
        st.rerun()

# ================= MAIN AREA (TERMINAL TOP HEADER) =================
@st.fragment(run_every="1s")
def terminal_fragment():
    sync_market_data()
    idxs = get_indices_snapshot()
    
    # Hand-drawn metrics row
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Live Price", f"₹{st.session_state.current_ltp:,.2f}")
    m2.metric("EMA 200", f"₹{st.session_state.live_ema:,.2f}")
    m3.metric("Balance", f"₹{st.session_state.current_balance:,.2f}")
    m4.metric("Nifty", idxs["NIFTY 50"]["lp"], delta=f"{idxs['NIFTY 50']['pc']}%")
    m5.metric("Sensex", idxs["SENSEX"]["lp"], delta=f"{idxs['SENSEX']['pc']}%")
    
    # Control Area: Chart Left (3.4), Activity Side (0.6)
    col_chart, col_logs = st.columns([3.4, 0.6])
    
    with col_chart:
        if st.session_state.ohlc_data:
            chart_options = {
                "height": 420, 
                "layout": {"background": {"color": "#0d1117"}, "textColor": "#d1d4dc"},
                "timeScale": {"timeVisible": True, "secondsVisible": True},
                "rightPriceScale": {"visible": True, "borderVisible": False},
                "grid": {"vertLines": {"color": "#161b22"}, "horzLines": {"color": "#161b22"}}
            }
            series = [
                {"type": 'Candlestick', "data": st.session_state.ohlc_data, "options": {"upColor": '#26a69a', "downColor": '#ef5350', "borderVisible": False}},
                {"type": 'Line', "data": st.session_state.ema_data, "options": {"color": "#2196f3", "lineWidth": 2, "title": "EMA 200"}}
            ]
            if st.session_state.get("supertrend_data"):
                series.append({"type": 'Line', "data": st.session_state.supertrend_data, "options": {"lineWidth": 2, "title": "ST"}})
            
            renderCustomLightweightCharts([{"chart": chart_options, "series": series}], 'termi_v5')

    with col_logs:
        # EXPANDED ORDER CONSOLE
        st.markdown("<div style='color:#58a6ff; font-size:0.65rem; font-weight:800; margin-bottom:5px;'>🎯 ORDER CONSOLE</div>", unsafe_allow_html=True)
        with st.container(border=True):
            st.session_state.trade_tsym = st.text_input("SYMBOL", value=st.session_state.trade_tsym, key="tsym_console", label_visibility="collapsed")
            st.session_state.trade_qty = st.number_input("QTY", value=st.session_state.trade_qty, step=1, key="qty_console", label_visibility="collapsed")
            
            st.session_state.dashboard_exchange = st.selectbox("EXCH", ["MCX", "NFO", "CDS", "BFO", "NSE", "BSE"], 
                                                             index=["MCX", "NFO", "CDS", "BFO", "NSE", "BSE"].index(st.session_state.dashboard_exchange),
                                                             key="exch_console", label_visibility="collapsed")
            
            st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True) # Spacer for size
            btn_txt = "🛑 STOP" if st.session_state.auto_trading_active else "🚀 START ORDER"
            btn_clr = "secondary" if st.session_state.auto_trading_active else "primary"
            if st.button(btn_txt, type=btn_clr, use_container_width=True, key="console_start"):
                st.session_state.auto_trading_active = not st.session_state.auto_trading_active
                st.session_state.trading_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] Console: {'Started' if st.session_state.auto_trading_active else 'Stopped'}")
                st.rerun()
        
        st.markdown("<div style='font-size:0.55rem; font-weight:800; color:#58a6ff; margin-bottom:4px; margin-top:8px;'>📜 FEED</div>", unsafe_allow_html=True)
        log_box = st.container(height=140) # Further reduced to prioritize the console
        with log_box:
            for log in reversed(st.session_state.trading_logs):
                st.markdown(f"<p style='font-size:0.55rem; color:#d1d4dc; margin:0; padding:3px 0; border-bottom:1px solid #30363d;'>{log}</p>", unsafe_allow_html=True)

terminal_fragment()
