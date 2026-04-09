import json
import time
import os
import requests
import sys
from datetime import datetime

# ================= CONFIG =================
DATA_FILE = "flattrade_indices.json"     # For sidebar metrics
MARKET_DATA_FILE = "market_data.json"    # For main chart and bot
AUTH_FILE = "flattrade_auth.json"
CREDS_FILE = "credentials.json"
CONFIG_FILE = "dashboard_config.json"
PID_FILE = "flattrade_indices.pid"
STOP_FILE = "stop_indices.txt"
URL = "https://piconnect.flattrade.in/PiConnectAPI/GetQuotes"

EMA_PERIOD = 200
SUPERTREND_PERIOD = 10

class UnifiedBackend:
    def __init__(self):
        self.jkey = None
        self.uid = None
        self.ohlc_bars = []
        self.ema_bars = []
        self.supertrend_bars = []
        self.current_bar = {"open": None, "high": -float("inf"), "low": float("inf"), "close": None, "volume": 0}
        self.latest_ltp = 0.0
        
        # Supertrend state
        self.tr_list = []
        self.atr_list = []
        self.final_upperband_list = []
        self.final_lowerband_list = []
        self.st_trend_list = []
        self.proxies = None
        self.load_proxies()

    def load_proxies(self):
        try:
            # Try secrets first (Cloud)
            try:
                import streamlit as st
                if 'FT_PROXY_HOST' in st.secrets and str(st.secrets.get('FT_USE_PROXY', 'false')).lower() == 'true':
                    p_host = st.secrets['FT_PROXY_HOST']
                    p_port = st.secrets.get('FT_PROXY_PORT', '1080')
                    p_user = st.secrets.get('FT_PROXY_USER', '')
                    p_pass = st.secrets.get('FT_PROXY_PASS', '')
                    if p_user and p_pass:
                        p_url = f"socks5h://{p_user}:{p_pass}@{p_host}:{p_port}"
                    else:
                        p_url = f"socks5h://{p_host}:{p_port}"
                    self.proxies = {"http": p_url, "https": p_url}
                    print(f"Proxy configured for UnifiedBackend via Secrets: {p_host}")
                    return
            except: pass

            # Fallback to local files
            if os.path.exists(CREDS_FILE):
                with open(CREDS_FILE, "r") as f:
                    creds = json.load(f)
                    if creds.get('use_proxy') and creds.get('proxy_host'):
                        p_host = creds.get('proxy_host')
                        p_port = creds.get('proxy_port', '1080')
                        p_user = creds.get('proxy_user', '')
                        p_pass = creds.get('proxy_pass', '')
                        if p_user and p_pass:
                            p_url = f"socks5h://{p_user}:{p_pass}@{p_host}:{p_port}"
                        else:
                            p_url = f"socks5h://{p_host}:{p_port}"
                        self.proxies = {"http": p_url, "https": p_url}
                        print(f"Proxy configured for UnifiedBackend via File: {p_host}")
        except Exception as e:
            print(f"Error loading proxies: {e}")

    def check_singleton(self):
        if os.path.exists(PID_FILE):
            try:
                with open(PID_FILE, "r") as f:
                    old_pid = int(f.read().strip())
                import psutil
                if psutil.pid_exists(old_pid):
                    return False
            except Exception:
                pass
        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))
        return True

    def cleanup(self):
        if os.path.exists(PID_FILE):
            try: os.remove(PID_FILE)
            except: pass

    def load_auth(self):
        try:
            if os.path.exists(AUTH_FILE):
                with open(AUTH_FILE, "r") as f:
                    self.jkey = json.load(f)["token"]
            if os.path.exists(CREDS_FILE):
                with open(CREDS_FILE, "r") as f:
                    self.uid = json.load(f)["username"]
            return self.jkey and self.uid
        except:
            return False

    def add_tick(self, ltp, qty, ts, range_size, token_id):
        self.latest_ltp = ltp
        if self.current_bar["open"] is None:
            self.current_bar = {"open": ltp, "high": ltp, "low": ltp, "close": ltp, "volume": 0}

        self.current_bar["high"] = max(self.current_bar["high"], ltp)
        self.current_bar["low"] = min(self.current_bar["low"], ltp)
        self.current_bar["close"] = ltp
        self.current_bar["volume"] += qty

        if (self.current_bar["high"] - self.current_bar["low"]) >= range_size:
            chart_time = int(ts)
            if self.ohlc_bars and chart_time <= self.ohlc_bars[-1]["time"]:
                chart_time = self.ohlc_bars[-1]["time"] + 1
            
            bar = {
                "time": chart_time,
                "open": self.current_bar["open"],
                "high": self.current_bar["high"],
                "low": self.current_bar["low"],
                "close": self.current_bar["close"],
                "volume": self.current_bar["volume"]
            }
            self.ohlc_bars.append(bar)
            
            # EMA Calculation
            if len(self.ohlc_bars) > 0:
                cur_close = bar["close"]
                if not self.ema_bars:
                    self.ema_bars.append({"time": chart_time, "value": cur_close})
                else:
                    prev_ema = self.ema_bars[-1]["value"]
                    mult = 2 / (EMA_PERIOD + 1)
                    ema_val = (cur_close - prev_ema) * mult + prev_ema
                    self.ema_bars.append({"time": chart_time, "value": ema_val})

            # Supertrend 
            if len(self.ohlc_bars) > 0 and len(self.ema_bars) > 0:
                hi, lo, cl = bar["high"], bar["low"], bar["close"]
                tr = hi - lo if len(self.ohlc_bars) == 1 else max(hi - lo, abs(hi - self.ohlc_bars[-2]["close"]), abs(lo - self.ohlc_bars[-2]["close"]))
                self.tr_list.append(tr)
                
                if not self.atr_list: self.atr_list.append(tr)
                else:
                    prev_atr = self.atr_list[-1]
                    atr_mult = 2 / (SUPERTREND_PERIOD + 1)
                    self.atr_list.append((tr - prev_atr) * atr_mult + prev_atr)
                
                basis = self.ema_bars[-1]["value"]
                cur_atr = self.atr_list[-1]
                st_mult = 0.0 # Standard for this strategy
                
                up, dn = basis + (st_mult * cur_atr), basis - (st_mult * cur_atr)
                
                if not self.final_upperband_list:
                    self.final_upperband_list.append(up); self.final_lowerband_list.append(dn); self.st_trend_list.append(1)
                    self.supertrend_bars.append({"time": chart_time, "value": dn, "trend": 1})
                else:
                    p_up, p_dn, p_trend = self.final_upperband_list[-1], self.final_lowerband_list[-1], self.st_trend_list[-1]
                    p_src = self.ema_bars[-2]["value"] if len(self.ema_bars) > 1 else basis
                    
                    f_up = up if (up < p_up or p_src > p_up) else p_up
                    f_dn = dn if (dn > p_dn or p_src < p_dn) else p_dn
                    
                    trend = p_trend
                    if p_trend == 1 and basis < f_dn: trend = -1
                    elif p_trend == -1 and basis > f_up: trend = 1
                    
                    self.final_upperband_list.append(f_up); self.final_lowerband_list.append(f_dn); self.st_trend_list.append(trend)
                    self.supertrend_bars.append({"time": chart_time, "value": f_dn if trend == 1 else f_up, "trend": trend})

            # Cleanup old data
            if len(self.ohlc_bars) > 500:
                for lst in [self.ohlc_bars, self.ema_bars, self.supertrend_bars, self.tr_list, self.atr_list, self.final_upperband_list, self.final_lowerband_list, self.st_trend_list]:
                    if lst: lst.pop(0)

            self.current_bar = {"open": None, "high": -float("inf"), "low": float("inf"), "close": None, "volume": 0}

    def run(self):
        if not self.check_singleton(): return
        if not self.load_auth(): return self.cleanup()
        
        indices_state = {"NIFTY 50": {"lp": "N/A", "pc": "0.00"}, "SENSEX": {"lp": "N/A", "pc": "0.00"}}
        print("Unified Backend Running...")

        while not os.path.exists(STOP_FILE):
            try:
                # 1. Global Indices Polling
                for exch, tok, name in [("NSE", "26000", "NIFTY 50"), ("BSE", "1", "SENSEX")]:
                    payload = 'jData=' + json.dumps({"uid": self.uid, "exch": exch, "token": tok}) + '&jKey=' + self.jkey
                    res = requests.post(URL, data=payload, proxies=self.proxies, timeout=5).json()
                    if res.get('stat') == 'Ok':
                        lp, c = float(res.get('lp', 0)), float(res.get('c', 1))
                        indices_state[name] = {"lp": f"{lp:.2f}", "pc": f"{((lp-c)/c*100):.2f}"}

                with open(DATA_FILE + ".tmp", "w") as f: json.dump({"prices": indices_state, "last_update": time.time()}, f)
                os.replace(DATA_FILE + ".tmp", DATA_FILE)

                # 2. Dynamic Dashboard Token Polling
                if os.path.exists(CONFIG_FILE):
                    with open(CONFIG_FILE, "r") as f: conf = json.load(f)
                    tok, exch, rng = conf.get("token"), conf.get("exch"), float(conf.get("range", 0.05))
                    
                    if tok and exch:
                        payload = 'jData=' + json.dumps({"uid": self.uid, "exch": exch, "token": tok}) + '&jKey=' + self.jkey
                        res = requests.post(URL, data=payload, proxies=self.proxies, timeout=5).json()
                        if res.get('stat') == 'Ok':
                            lp = float(res.get('lp', 0))
                            qty = int(res.get('v', 0)) # Using total volume as tick volume proxy
                            self.add_tick(lp, qty, time.time(), rng, tok)

                        # Save Market Data for Chart/Bot
                        l_ema, l_st, l_tr = 0.0, 0.0, 1
                        if self.ema_bars:
                            mult = 2 / (EMA_PERIOD + 1)
                            l_ema = (self.latest_ltp - self.ema_bars[-1]["value"]) * mult + self.ema_bars[-1]["value"]
                            if self.atr_list and self.st_trend_list:
                                l_tr = self.st_trend_list[-1]
                                l_st = self.final_lowerband_list[-1] if l_tr == 1 else self.final_upperband_list[-1]

                        mdata = {
                            "ltp": self.latest_ltp, "ohlc": self.ohlc_bars, "ema": self.ema_bars, "supertrend": self.supertrend_bars,
                            "live_ema": l_ema, "live_strend": l_st, "live_trend": l_tr, "last_update": time.time(), "token_id": tok
                        }
                        with open(MARKET_DATA_FILE + ".tmp", "w") as f: json.dump(mdata, f)
                        os.replace(MARKET_DATA_FILE + ".tmp", MARKET_DATA_FILE)

            except Exception as e:
                print(f"Loop Error: {e}")
            time.sleep(1.5)

        if os.path.exists(STOP_FILE): os.remove(STOP_FILE)
        self.cleanup()

if __name__ == "__main__":
    UnifiedBackend().run()
