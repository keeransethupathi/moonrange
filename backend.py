import json
import pandas as pd
import numpy as np
from datetime import datetime
import threading
import time
import os
from SmartApi.smartWebSocketV2 import SmartWebSocketV2
from logzero import logger
import traceback
import sys
import sqlite3

# ================= CONFIG v2.3 =================
# Default values
default_exchange = 5
default_token = "486503"

# Load from arguments if provided
exchange_type = int(sys.argv[1]) if len(sys.argv) > 1 else default_exchange
token_id = sys.argv[2] if len(sys.argv) > 2 else default_token
range_bar_size_arg = float(sys.argv[3]) if len(sys.argv) > 3 else 0.05

# 1R configuration: 1.0 means 1 point. Change to 0.05 if 1R means exactly 1 tick for Nifty.
RANGE_BAR_SIZE = range_bar_size_arg
EMA_PERIOD = 200
SUPERTREND_PERIOD = 10
TOKEN_LIST = [{"exchangeType": exchange_type, "tokens": [token_id]}]
CORRELATION_ID = f"backend_{token_id}"
DATA_FILE = "market_data.json"
STOP_FILE = "stop_backend.txt"

# ================= STATE & LOGIC =================
class MarketDataBackend:
    def __init__(self):
        self.lock = threading.Lock()
        self.ohlc_bars = []
        self.ema_bars = []
        self.supertrend_bars = []
        self.raw_bars = []
        self.current_bar = {"open": None, "high": -float("inf"), "low": float("inf"), "close": None, "ticks": 0, "volume": 0}
        self.latest_ltp = 0.0
        self.sws = None
        
        # Database initialization for persistent saving
        try:
            self.db_conn = sqlite3.connect("market_data.db", check_same_thread=False)
            self.db_cursor = self.db_conn.cursor()
            self.db_cursor.execute('''CREATE TABLE IF NOT EXISTS ohlc (
                                time INTEGER,
                                open REAL, high REAL, low REAL, close REAL, volume INTEGER,
                                token_id TEXT,
                                UNIQUE(time, token_id)
                            )''')
            self.db_conn.commit()
        except Exception as e:
            logger.error(f"DB init error: {e}")

    def on_open(self, wsapp):
        logger.info("### [v2.0] WebSocket Connected Successfully ###")
        try:
            # Small delay to ensure handshake is fully processed by the server
            time.sleep(2)
            self.sws.subscribe(CORRELATION_ID, 3, TOKEN_LIST)
            logger.info(f"### [v2.0] Subscription request sent for {TOKEN_LIST} ###")
        except Exception as e:
            logger.error(f"Subscription Error: {e}")

    def on_data(self, wsapp, message):
        if not message:
            return

        # SmartApi often sends messages as a list
        if isinstance(message, list):
            for msg in message:
                self.process_message(msg)
        else:
            self.process_message(message)

    def process_message(self, message):
        if isinstance(message, dict) and "last_traded_price" in message:
            try:
                ltp = message["last_traded_price"] / 100
                qty = message.get("last_traded_quantity") or 1
                ts_raw = message.get("exchange_timestamp")
                if ts_raw:
                    # Detect if timestamp is in milliseconds or seconds
                    if ts_raw > 10**12: # milliseconds (typical for 2024+ epochs)
                        ts = datetime.fromtimestamp(ts_raw / 1000)
                    else: # seconds
                        ts = datetime.fromtimestamp(ts_raw)
                else:
                    ts = datetime.now()
                
                logger.info(f"Tick received: LTP={ltp}, Qty={qty}, TS={ts}")
                self.add_tick(ltp, qty, ts)
            except Exception as e:
                logger.error(f"Tick processing error: {e}")
                logger.error(traceback.format_exc())
        else:
            msg_str = str(message).lower()
            if "heartbeat" not in msg_str and "success" not in msg_str:
                logger.info(f"Other WS message: {message}")

    def on_error(self, wsapp, error):
        logger.error(f"### [v2.0] WebSocket Error: {error} ###")
        logger.error(traceback.format_exc())

    def on_close(self, wsapp, code=None, msg=None):
        logger.warn(f"### [v2.0] WebSocket Closed: {code} - {msg} ###")

    def add_tick(self, ltp, qty, ts):
        with self.lock:
            self.latest_ltp = ltp
            if self.current_bar["open"] is None:
                self.current_bar["open"] = ltp
                self.current_bar["high"] = ltp
                self.current_bar["low"] = ltp
                self.current_bar["close"] = ltp
                self.current_bar["ticks"] = 0
                self.current_bar["volume"] = 0

            self.current_bar["high"] = max(self.current_bar["high"], ltp)
            self.current_bar["low"] = min(self.current_bar["low"], ltp)
            self.current_bar["close"] = ltp
            self.current_bar["ticks"] += 1
            self.current_bar["volume"] += qty

            # Range 1R condition
            if (self.current_bar["high"] - self.current_bar["low"]) >= RANGE_BAR_SIZE:
                # Use raw UTC timestamp for chart consistency
                chart_time = int(ts.timestamp())
                
                # Lightweight Charts requires strictly increasing unique timestamps
                if len(self.ohlc_bars) > 0 and chart_time <= self.ohlc_bars[-1]["time"]:
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
                self.raw_bars.append(bar)
                
                # Save to automatic database file
                try:
                    self.db_cursor.execute("INSERT OR IGNORE INTO ohlc (time, open, high, low, close, volume, token_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (chart_time, bar["open"], bar["high"], bar["low"], bar["close"], bar["volume"], str(token_id)))
                    self.db_conn.commit()
                except Exception as e:
                    logger.error(f"DB save error: {e}")
                
                # EMA Logic (200 period)
                if len(self.ohlc_bars) > 0:
                    current_close = self.ohlc_bars[-1]["close"]
                    if len(self.ema_bars) == 0:
                        # Initialize EMA with the first close
                        self.ema_bars.append({"time": chart_time, "value": current_close})
                    else:
                        prev_ema = self.ema_bars[-1]["value"]
                        multiplier = 2 / (EMA_PERIOD + 1)
                        ema_val = (current_close - prev_ema) * multiplier + prev_ema
                        self.ema_bars.append({"time": chart_time, "value": ema_val})

                # Supertrend Logic (10, EMA: EMA)
                # First compute True Range and ATR (EMA of TR)
                if len(self.ohlc_bars) > 0:
                    current_high = self.ohlc_bars[-1]["high"]
                    current_low = self.ohlc_bars[-1]["low"]
                    current_close = self.ohlc_bars[-1]["close"]
                    
                    # True Range
                    if len(self.ohlc_bars) == 1:
                        tr = current_high - current_low
                    else:
                        prev_close = self.ohlc_bars[-2]["close"]
                        tr = max(current_high - current_low, abs(current_high - prev_close), abs(current_low - prev_close))
                    
                    # Store TR temporarily to compute ATR (EMA of TR)
                    if not hasattr(self, 'tr_list'):
                        self.tr_list = []
                    self.tr_list.append(tr)
                    
                    # ATR (EMA of TR)
                    if not hasattr(self, 'atr_list'):
                        self.atr_list = []
                    
                    if len(self.atr_list) == 0:
                        self.atr_list.append(tr)
                    else:
                        prev_atr = self.atr_list[-1]
                        atr_multiplier = 2 / (SUPERTREND_PERIOD + 1)
                        current_atr = (tr - prev_atr) * atr_multiplier + prev_atr
                        self.atr_list.append(current_atr)
                        
                    # Calculate basic upper and lower bands based on EMA instead of (High+Low)/2
                    if len(self.ema_bars) > 0:
                        basis = self.ema_bars[-1]["value"]
                        current_atr_val = self.atr_list[-1]
                        
                        # Note: The image says "ATR Factor 0" or (10, EMA: EMA, 0)
                        # If multiplier is 0, the upper and lower bands are just the EMA.
                        # Wait, TradingView Supertrend needs a multiplier. Let's use standard ATR multiplier (e.g., 3) if 0 is a placeholder,
                        # or if it strictly means 0, the Bands equal the EMA. We'll use a configurable multiplier.
                        # Using 3 as standard default if 0 implies no dynamic multiplier but a default.
                        # Using 0.0 as requested
                        ST_MULTIPLIER = 0.0 
                        
                        basic_upperband = basis + (ST_MULTIPLIER * current_atr_val)
                        basic_lowerband = basis - (ST_MULTIPLIER * current_atr_val)
                        
                        if not hasattr(self, 'final_upperband_list'):
                            self.final_upperband_list = []
                            self.final_lowerband_list = []
                            self.st_trend_list = [] # 1 for uptrend, -1 for downtrend
                        
                        if len(self.final_upperband_list) == 0:
                            self.final_upperband_list.append(basic_upperband)
                            self.final_lowerband_list.append(basic_lowerband)
                            self.st_trend_list.append(1)
                            self.supertrend_bars.append({"time": chart_time, "value": basic_lowerband, "trend": 1})
                        else:
                            prev_final_upperband = self.final_upperband_list[-1]
                            prev_final_lowerband = self.final_lowerband_list[-1]
                            # Use EMA instead of close for crossovers (source of supertrend = ema)
                            prev_source = self.ema_bars[-2]["value"] if len(self.ema_bars) > 1 else basis
                            current_source = basis
                            prev_trend = self.st_trend_list[-1]
                            
                            # Final Upper Band
                            if basic_upperband < prev_final_upperband or prev_source > prev_final_upperband:
                                final_upperband = basic_upperband
                            else:
                                final_upperband = prev_final_upperband
                                
                            # Final Lower Band
                            if basic_lowerband > prev_final_lowerband or prev_source < prev_final_lowerband:
                                final_lowerband = basic_lowerband
                            else:
                                final_lowerband = prev_final_lowerband
                                
                            # Trend Crossover using EMA (current_source) instead of close
                            if prev_trend == 1 and current_source < final_lowerband:
                                trend = -1
                            elif prev_trend == -1 and current_source > final_upperband:
                                trend = 1
                            else:
                                trend = prev_trend
                                
                            self.final_upperband_list.append(final_upperband)
                            self.final_lowerband_list.append(final_lowerband)
                            self.st_trend_list.append(trend)
                            
                            st_value = final_lowerband if trend == 1 else final_upperband
                            self.supertrend_bars.append({"time": chart_time, "value": st_value, "trend": trend})

                if len(self.ohlc_bars) > 1000:
                    self.ohlc_bars.pop(0)
                    if self.ema_bars: self.ema_bars.pop(0)
                    if self.supertrend_bars: self.supertrend_bars.pop(0)
                    if hasattr(self, 'tr_list') and len(self.tr_list) > 1000: self.tr_list.pop(0)
                    if hasattr(self, 'atr_list') and len(self.atr_list) > 1000: self.atr_list.pop(0)
                    if hasattr(self, 'final_upperband_list') and len(self.final_upperband_list) > 1000:
                        self.final_upperband_list.pop(0)
                        self.final_lowerband_list.pop(0)
                        self.st_trend_list.pop(0)
                
                self.current_bar = {"open": None, "high": -float("inf"), "low": float("inf"), "close": None, "ticks": 0, "volume": 0}
                self.save_data()

    def save_data(self):
        try:
            # LIVE UNCLOSED INDICATOR CALCULATIONS
            live_ema = 0.0
            live_strend = 0.0
            live_trend = 1
            current_close = float(self.latest_ltp)
            
            if current_close > 0:
                # Live EMA
                if len(self.ema_bars) > 0:
                    prev_ema = self.ema_bars[-1]["value"]
                    multiplier = 2 / (EMA_PERIOD + 1)
                    live_ema = (current_close - prev_ema) * multiplier + prev_ema
                else:
                    live_ema = current_close
                    
                # Live Supertrend
                if len(self.ohlc_bars) > 0 and hasattr(self, 'atr_list') and len(self.atr_list) > 0:
                    current_high = max(self.current_bar["high"], current_close) if self.current_bar["high"] != -float("inf") else current_close
                    current_low = min(self.current_bar["low"], current_close) if self.current_bar["low"] != float("inf") else current_close
                    prev_close = self.ohlc_bars[-1]["close"]
                    
                    tr = max(current_high - current_low, abs(current_high - prev_close), abs(current_low - prev_close))
                    prev_atr = self.atr_list[-1]
                    atr_multiplier = 2 / (SUPERTREND_PERIOD + 1)
                    live_atr = (tr - prev_atr) * atr_multiplier + prev_atr
                    
                    basic_upperband = live_ema + (0.0 * live_atr)
                    basic_lowerband = live_ema - (0.0 * live_atr)
                    
                    if hasattr(self, 'final_upperband_list') and len(self.final_upperband_list) > 0:
                        prev_final_upperband = self.final_upperband_list[-1]
                        prev_final_lowerband = self.final_lowerband_list[-1]
                        prev_trend = self.st_trend_list[-1]
                        
                        # Use EMA instead of close for live crossovers
                        prev_source = self.ema_bars[-1]["value"] if len(self.ema_bars) > 0 else prev_close
                        current_source = live_ema
                        
                        live_final_upperband = basic_upperband if (basic_upperband < prev_final_upperband or prev_source > prev_final_upperband) else prev_final_upperband
                        live_final_lowerband = basic_lowerband if (basic_lowerband > prev_final_lowerband or prev_source < prev_final_lowerband) else prev_final_lowerband
                        
                        # Live Trend Crossover using Live EMA
                        if prev_trend == 1 and current_source < live_final_lowerband:
                            live_trend = -1
                        elif prev_trend == -1 and current_source > live_final_upperband:
                            live_trend = 1
                        else:
                            live_trend = prev_trend
                            
                        live_strend = live_final_lowerband if live_trend == 1 else live_final_upperband
                else:
                    live_strend = current_close

            data = {
                "ltp": current_close,
                "ohlc": self.ohlc_bars,
                "ema": self.ema_bars,
                "supertrend": self.supertrend_bars,
                "live_ema": live_ema,
                "live_strend": live_strend,
                "live_trend": live_trend,
                "version": "4.1",
                "last_update": time.time(),
                "token_id": str(token_id),
                "exchange_type": int(exchange_type)
            }
            # Save locally with retry logic for Windows file locks
            temp_file = DATA_FILE + ".tmp"
            with open(temp_file, "w") as f:
                json.dump(data, f)
            
            # Use small retry loop for os.replace to handle Windows file locking issues
            for _ in range(3):
                try:
                    os.replace(temp_file, DATA_FILE)
                    break
                except PermissionError:
                    time.sleep(0.1)
            
            # (Firebase code removed)
                
        except Exception as e:
            logger.error(f"Data save error: {e}")

    def run(self):
        logger.info("### [v2.0] Starting Backend System ###")
        if os.path.exists(STOP_FILE):
            os.remove(STOP_FILE)
            
        try:
            with open("auth.json", "r") as f:
                auth = json.load(f)
            
            # Using raw token as in original working script
            token = auth["Authorization"]
            
            self.sws = SmartWebSocketV2(token, auth["api_key"], auth["client_code"], auth["feedtoken"])
            self.sws.on_open = self.on_open
            self.sws.on_data = self.on_data
            self.sws.on_error = self.on_error
            self.sws.on_close = self.on_close
            
            logger.info(f"### [v2.0] Connecting client {auth['client_code']} ###")
            
            ws_thread = threading.Thread(target=self.sws.connect, daemon=True)
            ws_thread.start()
            
            while True:
                if os.path.exists(STOP_FILE):
                    logger.info("### [v2.0] Stop signal detected. Shutting down sws... ###")
                    self.sws.close_connection()
                    break
                # Refresh data file every 1 second to keep 'running' state in frontend
                self.save_data()
                time.sleep(1)
        except Exception as e:
            logger.error(f"Main loop error: {e}")
            logger.error(traceback.format_exc())
        finally:
            logger.info("### [v2.0] Backend Shutdown Complete ###")

if __name__ == "__main__":
    backend = MarketDataBackend()
    backend.run()
