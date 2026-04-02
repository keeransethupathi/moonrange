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

    api_key = creds.get("api_key", "").strip()
    api_secret = creds.get("api_secret", "").strip()
    
    if not api_key or not api_secret:
        print("❌ Error: credentials.json is missing api_key or api_secret.")
        return

    print(f"Using API Key ending in: ...{api_key[-4:]}")
    print(f"Using API Secret ending in: ...{api_secret[-4:]}")

    # 2. Get Request Code Directly (Eliminate URL bugs)
    print("\nStep 1: Open Flattrade Login, authorize, and land on Google.")
    print("Step 2: Copy ONLY the 'code' from the URL (e.g., becf7...)")
    request_code = input("Step 3: Paste the Request Code here: \n> ").strip()
    
    if not request_code:
        print("❌ Error: Request Code cannot be empty.")
        return

    try:
        # Diagnostic: Show IP to verify we are on a residential network
        print("\n--- Network Diagnostics ---")
        try:
            v4 = requests.get('https://api.ipify.org', timeout=5).text
            print(f"IPv4 Detected: {v4}")
        except: print("IPv4: Error (Check internet)")
        
        try:
            v6 = requests.get('https://api6.ipify.org', timeout=5).text
            print(f"IPv6 Detected: {v6}")
        except: print("IPv6: None/Not available")
        
        print(f"Captured Code: {request_code[:10]}...")

        # 3. Generate SHA256 Hash
        hash_payload = (api_key + request_code + api_secret).encode()
        hash_value = hashlib.sha256(hash_payload).hexdigest()

        # 4. Perform Exchange
        print("\nExchanging for Access Token...")
        url = "https://authapi.flattrade.in/trade/apitoken"
        payload = {
            "api_key": api_key,
            "request_code": request_code,
            "api_secret": hash_value
        }
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": "https://auth.flattrade.in",
            "Referer": "https://auth.flattrade.in/",
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=15)
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
