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

import sys

# ================= CONFIG v2.3 =================
# Default values
default_exchange = 5
default_token = "472789"

# Load from arguments if provided
exchange_type = int(sys.argv[1]) if len(sys.argv) > 1 else default_exchange
token_id = sys.argv[2] if len(sys.argv) > 2 else default_token

TICK_BAR_SIZE = 5
MCGINLEY_PERIOD = 20
MCGINLEY_K = 0.6
TOKEN_LIST = [{"exchangeType": exchange_type, "tokens": [token_id]}]
CORRELATION_ID = f"backend_{token_id}"
DATA_FILE = "market_data.json"
STOP_FILE = "stop_backend.txt"

# ================= STATE & LOGIC =================
class MarketDataBackend:
    def __init__(self):
        self.lock = threading.Lock()
        self.ohlc_bars = []
        self.mdi_bars = []
        self.raw_bars = []
        self.current_bar = {"open": None, "high": -float("inf"), "low": float("inf"), "close": None, "ticks": 0, "volume": 0}
        self.latest_ltp = 0.0
        self.sws = None

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
        if message and isinstance(message, dict) and "last_traded_price" in message:
            try:
                ltp = message["last_traded_price"] / 100
                qty = message.get("last_traded_quantity") or 1
                ts = datetime.fromtimestamp(message["exchange_timestamp"] / 1000)
                self.add_tick(ltp, qty, ts)
            except Exception as e:
                logger.error(f"Tick processing error: {e}")
        else:
            if "heartbeat" not in str(message).lower():
                logger.info(f"Other WS message: {message}")

    def on_error(self, wsapp, error):
        logger.error(f"### [v2.0] WebSocket Error: {error} ###")

    def on_close(self, wsapp, code, msg):
        logger.warn(f"### [v2.0] WebSocket Closed: {code} - {msg} ###")

    def add_tick(self, ltp, qty, ts):
        with self.lock:
            self.latest_ltp = ltp
            if self.current_bar["open"] is None:
                self.current_bar["open"] = ltp
            self.current_bar["high"] = max(self.current_bar["high"], ltp)
            self.current_bar["low"] = min(self.current_bar["low"], ltp)
            self.current_bar["close"] = ltp
            self.current_bar["ticks"] += 1
            self.current_bar["volume"] += qty

            if self.current_bar["ticks"] >= TICK_BAR_SIZE:
                # Add 5 hours 30 minutes (19800 seconds) for IST display correction
                chart_time = int(ts.timestamp()) + 19800
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
                
                # McGinley Dynamic Logic
                # Formula: MD = MD_prev + (Price - MD_prev) / (K * N * (Price / MD_prev)**4)
                price = bar["close"]
                if not self.mdi_bars:
                    # Initialize with first close price
                    self.mdi_bars.append({"time": chart_time, "value": price})
                else:
                    prev_mdi = self.mdi_bars[-1]["value"]
                    # Prevent division by zero
                    if prev_mdi == 0: prev_mdi = price
                    
                    mdi_val = prev_mdi + (price - prev_mdi) / (MCGINLEY_K * MCGINLEY_PERIOD * (price / prev_mdi)**4)
                    self.mdi_bars.append({"time": chart_time, "value": float(mdi_val)})
                
                if len(self.ohlc_bars) > 500:
                    self.ohlc_bars.pop(0)
                    if self.mdi_bars: self.mdi_bars.pop(0)
                
                self.current_bar = {"open": None, "high": -float("inf"), "low": float("inf"), "close": None, "ticks": 0, "volume": 0}
                self.save_data()

    def save_data(self):
        try:
            data = {
                "ltp": float(self.latest_ltp),
                "ohlc": self.ohlc_bars,
                "mdi": self.mdi_bars,
                "last_update": time.time(),
                "token_id": str(token_id),
                "exchange_type": int(exchange_type)
            }
            # Save locally
            temp_file = DATA_FILE + ".tmp"
            with open(temp_file, "w") as f:
                json.dump(data, f)
            os.replace(temp_file, DATA_FILE)
            
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
                    self.sws.close()
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
