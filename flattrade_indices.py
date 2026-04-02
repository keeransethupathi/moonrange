import json
import time
import os
import requests
import sys

# ================= CONFIG =================
DATA_FILE = "flattrade_indices.json"
AUTH_FILE = "flattrade_auth.json"
CREDS_FILE = "credentials.json"
PID_FILE = "flattrade_indices.pid"
STOP_FILE = "stop_indices.txt"
URL = "https://piconnect.flattrade.in/PiConnectAPI/GetQuotes"

def check_singleton():
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

def cleanup():
    if os.path.exists(PID_FILE):
        try:
            os.remove(PID_FILE)
        except:
            pass

def main():
    if not check_singleton():
        print("Another instance is running.")
        return

    # Load Auth
    try:
        if os.path.exists(AUTH_FILE):
            with open(AUTH_FILE, "r") as f:
                jkey = json.load(f)["token"]
        else:
            jkey = os.environ.get("FT_TOKEN")
            
        if os.path.exists(CREDS_FILE):
            with open(CREDS_FILE, "r") as f:
                uid = json.load(f)["username"]
        else:
            uid = os.environ.get("FT_USERNAME")
            
        if not jkey or not uid:
            print("Auth missing.")
            return cleanup()
    except Exception as e:
        print("Auth load error:", e)
        return cleanup()

    prices = {
        "NIFTY 50": {"lp": "N/A", "pc": "0.00"},
        "SENSEX": {"lp": "N/A", "pc": "0.00"}
    }
    
    print("Starting REST Polling for Live Indices...")
    
    while not os.path.exists(STOP_FILE):
        try:
            for exch, tok, name in [("NSE", "26000", "NIFTY 50"), ("BSE", "1", "SENSEX")]:
                payload = 'jData=' + json.dumps({"uid": uid, "exch": exch, "token": tok}) + '&jKey=' + jkey
                headers = {'Content-Type': 'text/plain'}
                res = requests.post(URL, data=payload, headers=headers, timeout=5)
                
                if res.status_code == 200:
                    data = res.json()
                    if data.get('stat') == 'Ok':
                        lp = float(data.get('lp', '0'))
                        c = float(data.get('c', '1'))
                        pc = round(((lp - c) / c) * 100, 2) if c > 0 else 0.00
                        prices[name] = {"lp": f"{lp:.2f}", "pc": f"{pc:.2f}"}
            
            output = {"prices": prices, "last_update": time.time()}
            with open(DATA_FILE + ".tmp", "w") as f:
                json.dump(output, f)
            os.replace(DATA_FILE + ".tmp", DATA_FILE)
            
        except Exception as e:
            print(f"Polling Error: {e}")
            
        time.sleep(2) # Poll every 2 seconds

    print("Stop signal received.")
    if os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)
    cleanup()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        cleanup()
