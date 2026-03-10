import json
import time
import os
import websocket
import threading
import sys
import hashlib
import ssl
from datetime import datetime

# ================= CONFIG =================
DATA_FILE = "flattrade_indices.json"
AUTH_FILE = "flattrade_auth.json"
CREDS_FILE = "credentials.json"
PID_FILE = "flattrade_indices.pid"
STOP_FILE = "stop_indices.txt"
WSS_URL = "wss://piconnect.flattrade.in/NorenWS/"

# Instrument Tokens
# Nifty 50: NSE|26000
# Sensex: BSE|1
TOKENS = ["NSE|26000", "BSE|1"]

class FlattradeIndicesBackend:
    def __init__(self):
        self.ws = None
        # prices[name] = {"lp": price, "pc": percentage_change}
        self.prices = {
            "NIFTY 50": {"lp": "N/A", "pc": "0.00"},
            "SENSEX": {"lp": "N/A", "pc": "0.00"}
        }
        self.token_map = {"26000": "NIFTY 50", "1": "SENSEX"}
        self.jkey = None
        self.uid = None
        self.running = True

    def check_singleton(self):
        if os.path.exists(PID_FILE):
            try:
                with open(PID_FILE, "r") as f:
                    old_pid = int(f.read().strip())
                # Check if process is still running
                import psutil
                if psutil.pid_exists(old_pid):
                    print(f"Another instance is already running (PID: {old_pid}). Exiting.")
                    return False
            except Exception:
                pass # PID file corrupted or psutil missing, proceed
        
        # Write current PID
        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))
        return True

    def cleanup(self):
        if os.path.exists(PID_FILE):
            try:
                os.remove(PID_FILE)
            except:
                pass
        print("Cleanup complete.")

    def heartbeat(self):
        """Updates last_update timestamp every 10 seconds to keep the service 'alive'."""
        while self.running:
            if os.path.exists(STOP_FILE):
                print("Stop signal received. Heartbeat stopping.")
                self.running = False
                if self.ws:
                    self.ws.close()
                break
            self.save_data()
            time.sleep(10)

    def load_auth(self):
        # Try local file first
        if os.path.exists(AUTH_FILE):
            with open(AUTH_FILE, "r") as f:
                auth_data = json.load(f)
                self.jkey = auth_data.get("token")
        
        # Fallback to environment variable
        if not self.jkey:
            self.jkey = os.environ.get("FT_TOKEN")
            
        if not self.jkey:
            print(f"Error: Access token not found (file or FT_TOKEN env var).")
            return False

        # Load UID from local file
        if os.path.exists(CREDS_FILE):
            try:
                with open(CREDS_FILE, "r") as f:
                    creds = json.load(f)
                    self.uid = creds.get("username")
            except:
                pass
        
        # Fallback to environment variable
        if not self.uid:
            self.uid = os.environ.get("FT_USERNAME")

        if not self.uid:
            print("Error: User ID not found (file or FT_USERNAME env var).")
            return False
            
        return True

    def on_open(self, ws):
        print("WebSocket Connected.")
        # Login
        login_data = {
            "t": "c",
            "uid": self.uid,
            "actid": self.uid,
            "source": "API",
            "susertoken": self.jkey
        }
        ws.send(json.dumps(login_data))
        print(f"Login request sent for {self.uid}")

    def on_message(self, ws, message):
        try:
            data = json.loads(message)
            task = data.get("t")
            
            if task == "ck": # Connection Ack
                if data.get("s") == "OK":
                    print("Login Successful.")
                    # Subscribe
                    sub_data = {
                        "t": "t", # Touch/Subscribe
                        "k": "#".join(TOKENS)
                    }
                    ws.send(json.dumps(sub_data))
                    print(f"Subscribed to {TOKENS}")
                else:
                    print(f"Login Failed: {data.get('emsg')}")
                
            elif task == "tf" or task == "tk": # Tick Feed
                token = data.get("tk")
                lp = data.get("lp") # Last Price
                pc = data.get("pc") # Percentage Change
                
                if token:
                    name = self.token_map.get(token)
                    if name:
                        if lp: self.prices[name]["lp"] = lp
                        if pc: self.prices[name]["pc"] = pc
                        self.save_data()
                        # print(f"Update: {name} = {lp}")
                        
        except Exception as e:
            print(f"Error processing message: {e}")

    def on_error(self, ws, error):
        print(f"WebSocket Error: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        print(f"WebSocket Closed: {close_status_code} - {close_msg}")

    def save_data(self):
        try:
            output = {
                "prices": self.prices,
                "last_update": time.time()
            }
            # Atomic save
            temp_file = DATA_FILE + ".tmp"
            with open(temp_file, "w") as f:
                json.dump(output, f)
            os.replace(temp_file, DATA_FILE)
        except Exception as e:
            print(f"Save error: {e}")

    def run(self):
        if not self.check_singleton():
            return

        if not self.load_auth():
            self.cleanup()
            return
            
        # Start heartbeat thread
        h_thread = threading.Thread(target=self.heartbeat, daemon=True)
        h_thread.start()

        try:
            # websocket.enableTrace(True)
            self.ws = websocket.WebSocketApp(
                WSS_URL,
                on_open=self.on_open,
                on_message=self.on_message,
                on_error=self.on_error,
                on_close=self.on_close
            )
            
            print(f"Connecting to {WSS_URL}...")
            self.ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
        except KeyboardInterrupt:
            print("Stopping...")
        finally:
            self.running = False
            self.cleanup()

if __name__ == "__main__":
    backend = FlattradeIndicesBackend()
    backend.run()
