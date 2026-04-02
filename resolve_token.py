import os
import json
import requests
import hashlib
import time

def resolve():
    print("--- Flattrade Local Token Resolver ---")
    print("This script uses your local IP to bypass cloud 'INVALID_IP' blocks.")
    
    # 1. Load Credentials
    creds = {}
    if os.path.exists("credentials.json"):
        with open("credentials.json", "r") as f:
            creds = json.load(f)
    else:
        print("❌ Error: credentials.json not found in this folder.")
        return

    # 2. Get Redirect URL
    url_input = input("\nStep 1: Open Flattrade Login and authorize.\nStep 2: Paste the FULL Google Redirect URL here: \n> ")
    
    try:
        # Extract request_code
        if "code=" not in url_input:
            print("❌ Error: Could not find 'code=' in the URL. Make sure you copied the whole address.")
            return
        
        request_code = url_input.split("code=")[1].split("&")[0]
        print(f"✅ Captured Code: {request_code[:10]}...")

        # 3. Generate SHA256 Hash
        api_key = creds.get("api_key")
        api_secret = creds.get("api_secret")
        
        if not api_key or not api_secret:
            print("❌ Error: credentials.json is missing api_key or api_secret.")
            return

        hash_payload = (api_key + request_code + api_secret).encode()
        hash_value = hashlib.sha256(hash_payload).hexdigest()

        # 4. Perform Exchange (From Home IP)
        print("Exchanging for Access Token...")
        url = "https://authapi.flattrade.in/trade/apitoken"
        payload = {
            "api_key": api_key,
            "request_code": request_code,
            "api_secret": hash_value
        }
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": "https://auth.flattrade.in",
            "Referer": "https://auth.flattrade.in/",
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        data = response.json()
        
        if data.get("stat") == "Ok":
            token = data.get("token")
            print(f"\n✅ SUCCESS! Your Session Token (jKey) is:\n\n{token}\n")
            
            # Save to flattrade_auth.json automatically
            auth_data = {"api_key": api_key, "token": token}
            with open("flattrade_auth.json", "w") as f:
                json.dump(auth_data, f, indent=4)
            print("💾 Token saved to 'flattrade_auth.json' successfully.")
            
        else:
            print(f"❌ API Error: {data.get('emsg', 'Unknown response content')}")
            if response.status_code != 200:
                print(f"HTTP Status: {response.status_code}")
                print(f"Raw Response: {response.text}")

    except Exception as e:
        print(f"❌ Resolver Failed: {e}")

    input("\nPress Enter to Exit...")

if __name__ == "__main__":
    resolve()
