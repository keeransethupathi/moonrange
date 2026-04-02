from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import undetected_chromedriver as uc
import requests
import hashlib
import time
import json
import pyotp
import os
import socket
import urllib3.util.connection as urllib3_cn

# Force IPv4 for the requests library to prevent Flattrade from receiving IPv6 connections and throwing INVALID_IP
def allowed_gai_family():
    return socket.AF_INET

# Patch urllib3.util.connection BEFORE any requests are made
try:
    import urllib3.util.connection as urllib3_cn
    urllib3_cn.allowed_gai_family = allowed_gai_family
except:
    pass

def get_outbound_ip():
    """Diagnostic helper to see which IP Flattrade sees"""
    try:
        return requests.get("https://api.ipify.org", timeout=5).text
    except:
        return "Unknown"

def auto_login(creds=None, headless=False, log_func=None):
    def log(msg):
        print(msg)
        if log_func:
            log_func(msg)

    # Load credentials if not provided
    if creds is None:
        # Try environment variables first
        creds = {
            'username': os.environ.get('FT_USERNAME'),
            'password': os.environ.get('FT_PASSWORD'),
            'totp_key': os.environ.get('FT_TOTP_KEY'),
            'api_key': os.environ.get('FT_API_KEY'),
            'api_secret': os.environ.get('FT_API_SECRET')
        }
        
        # Check if all required keys are found in environment
        if not all(creds.values()):
            print("Some credentials missing in environment, checking credentials.json...")
            if os.path.exists('credentials.json'):
                with open('credentials.json', 'r') as f:
                    file_creds = json.load(f)
                    # Use file values for only missing ones
                    for key in creds:
                        if not creds[key]:
                            creds[key] = file_creds.get(key)
            else:
                print("Error: credentials.json not found and environment variables missing.")
                return {"status": "error", "message": "Missing credentials"}

    # Generate TOTP
    if not creds.get('totp_key'):
        log("Error: Missing TOTP key in credentials.")
        return {"status": "error", "message": "Missing TOTP key"}
        
    totp = pyotp.TOTP(creds['totp_key'])
    token = totp.now()
    log(f"Generated TOTP: {token}")

    # Setup Selenium via undetected_chromedriver
    chrome_options = uc.ChromeOptions()
    
    # Use /tmp on Linux for chrome_profile to avoid permission/disk-full issues in fixed st.app containers
    if os.name != 'nt' or os.path.exists('/usr/bin/chromium'):
        user_data_dir = os.path.join('/tmp', 'chrome_profile')
    else:
        user_data_dir = os.path.join(os.getcwd(), 'chrome_profile')
        
    if not os.path.exists(user_data_dir):
        os.makedirs(user_data_dir, exist_ok=True)
    chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
    
    # Standard undetected_chromedriver stealth
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    # Let UC handle the User-Agent dynamically for better stealth
    chrome_options.add_argument("--disable-features=IsolateOrigins,site-per-process")

    if headless:
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--disable-software-rasterizer")
        chrome_options.add_argument("--shm-size=2gb")
        chrome_options.add_argument("--remote-debugging-port=9222")
        chrome_options.add_argument("--address-family=ipv4")
        
    driver = None
    try:
        # Navigate to login page
        auth_url = f"https://auth.flattrade.in/?app_key={creds['api_key']}"
        
        try:
            # Try undetected_chromedriver first (works best for local/Windows)
            # If we are on Streamlit Cloud (Linux), specify the chromium binary explicitly
            if os.path.exists('/usr/bin/chromium'):
                log("Detected Streamlit Cloud environment. Forcing Chromium path for UC.")
                chrome_options.binary_location = '/usr/bin/chromium'
                driver = uc.Chrome(options=chrome_options, browser_executable_path='/usr/bin/chromium', use_subprocess=True)
            else:
                driver = uc.Chrome(options=chrome_options, use_subprocess=True)
        except Exception as e:
            log(f"Undetected ChromeDriver setup failed: {e}")
            log("Attempting fallback to standard Selenium WebDriver...")
            try:
                from selenium.webdriver.chrome.service import Service
                
                # Setup standard chrome options by copying arguments to avoid incompatibilities
                std_options = webdriver.ChromeOptions()
                for arg in chrome_options.arguments:
                    std_options.add_argument(arg)
                
                if os.path.exists('/usr/bin/chromium'):
                    std_options.binary_location = '/usr/bin/chromium'
                    service = Service('/usr/bin/chromedriver')
                else:
                    from webdriver_manager.chrome import ChromeDriverManager
                    service = Service(ChromeDriverManager().install())
                    
                driver = webdriver.Chrome(service=service, options=std_options)
                log("Standard Selenium WebDriver launched successfully via fallback.")
            except Exception as e2:
                log(f"Standard Selenium fallback also failed: {e2}")
                return {"status": "error", "message": f"All Selenium setups failed. UC Error: {e}, Standard Error: {e2}"}

        # Disable webdriver flag via script
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        driver.get(auth_url)
        log(f"Navigated to login page: {auth_url.split('=')[0]}=...")
        time.sleep(3) # Give page more time to settle on cloud environments

        # Helper for resilient input
        def send_keys_resilient(xpath_list, value, label):
            if not value: return False
            for xpath in xpath_list:
                for attempt in range(3):
                    try:
                        element = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
                        wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
                        element.click()
                        time.sleep(0.2)
                        element.clear()
                        for char in value:
                            element.send_keys(char)
                        driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", element)
                        if element.get_attribute('value') == value:
                            log(f"Entered {label}")
                            return True
                    except Exception as ex:
                        log(f"Attempt {attempt+1} fail for {label}: {ex}")
                        time.sleep(0.5)
            return False

        # Fill credentials
        wait = WebDriverWait(driver, 15)
        if not send_keys_resilient(["//input[@placeholder='User ID']", "//input[@name='user_id']"], creds['username'], "username"):
            return {"status": "error", "message": "Failed to find username input"}
        if not send_keys_resilient(["//input[@placeholder='Password']", "//input[@name='password']"], creds['password'], "password"):
            return {"status": "error", "message": "Failed to find password input"}

        # Fill fresh TOTP
        token = pyotp.TOTP(creds['totp_key']).now()
        if not send_keys_resilient(["//input[@placeholder='OTP / TOTP']", "//input[@name='otp']"], token, "TOTP"):
            return {"status": "error", "message": "Failed to find TOTP input"}
        
        log("Proceeding to click Login...")
        time.sleep(1)

        try:
            # Direct JS Click is often most reliable for modern SPAs (Vuetify)
            login_btn_xpath = "//button[.//span[contains(text(), 'Log In')]] | //button[contains(., 'Log In')] | //button[contains(., 'Login')]"
            login_btn = wait.until(EC.element_to_be_clickable((By.XPATH, login_btn_xpath)))
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", login_btn)
            time.sleep(0.5)
            
            # Click via JS and PointerEvents to ensure a clean interaction
            js_login_script = """
            var btn = arguments[0];
            btn.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true}));
            btn.dispatchEvent(new PointerEvent('pointerup', {bubbles: true}));
            btn.click();
            """
            driver.execute_script(js_login_script, login_btn)
            log("Clicked login button via Direct JS Click / PointerEvents")
        except Exception as e:
            log(f"Login click failed: {e}")

        # Wait for redirect and capture code
        log("Waiting for redirect and handling potential modals...")
        try:
            # Wait for either the redirect URL OR the password change modal
            def wait_for_login_result(d):
                # 1. Check for success redirect
                if "code=" in d.current_url:
                    return True
                
                # 2. Check for the "Confirm Password Change" modal
                try:
                    confirm_btn = d.find_elements(By.XPATH, "//button[contains(., 'CONFIRM')]")
                    if confirm_btn and confirm_btn[0].is_displayed():
                        log("Detected 'Confirm Password Change' modal. Clicking CONFIRM...")
                        d.execute_script("arguments[0].click();", confirm_btn[0])
                        return False 
                except:
                    pass
                
                # 3. Check for specific error messages on page (e.g. Invalid password, Invalid TOTP, etc.)
                try:
                    # Look for red error text or snackbars
                    error_elements = d.find_elements(By.XPATH, "//*[contains(@class, 'error--text') or contains(@class, 'v-snack__content') or contains(@class, 'v-alert__content')]")
                    for elem in error_elements:
                        if elem.is_displayed() and elem.text:
                            log(f"Page Error Detected: {elem.text}")
                            # If we see a hard error, we can stop waiting
                            if any(msg in elem.text.lower() for msg in ["invalid", "incorrect", "expired", "required"]):
                                return True
                except:
                    pass

                # 4. Check for mandatory password change screen
                try:
                    if "Change password" in d.page_source or "new password" in d.page_source.lower():
                        log("Detected mandatory password change screen.")
                        return True
                except:
                    pass

                # 5. Check for specific error messages in URL
                if "error" in d.current_url.lower():
                    log(f"Error detected in URL: {d.current_url}")
                    return True
                    
                return False

            WebDriverWait(driver, 30).until(wait_for_login_result)
        except Exception as we:
            log(f"Wait for redirect/modal finished or timed out: {we}")
            
        current_url = driver.current_url
        log(f"Current URL: {current_url}")

        if 'code=' in current_url:
            request_code = current_url.split('code=')[1].split('&')[0]
            log(f"Captured request_code: {request_code}")
            
            # --- TOKEN GENERATION ---
            log("Generating final access token...")
            
            # 1. Try standard Python exchange first (Best for Local/Trusted IPs)
            res = generate_access_token(request_code, api_key=creds['api_key'], api_secret=creds['api_secret'])
            
            if res.get("status") == "success":
                log("✅ Python Token Exchange SUCCESSFUL!")
                return {"status": "success", "code": request_code, "token": res["token"]}
            
            # 2. If it failed with INVALID_IP, try the In-Browser Bypass (Best for Cloud)
            if "INVALID_IP" in str(res.get("message", "")):
                log("⚠️ Python Exchange failed with INVALID_IP. Attempting 'Form POST' Bypass...")
                
                hash_payload = (creds['api_key'] + request_code + creds['api_secret']).encode()
                hash_value = hashlib.sha256(hash_payload).hexdigest()
                
                # We use a standard HTML form submission to bypass XHR/CORS IP filters
                submit_js = """
                var form = document.createElement('form');
                form.method = 'POST';
                form.action = 'https://authapi.flattrade.in/trade/apitoken';
                
                var p = {
                    "api_key": arguments[0],
                    "request_code": arguments[1],
                    "api_secret": arguments[2]
                };
                
                // For Flattrade V2, we send the JSON in a hidden input or as the raw body
                // Actually, most Noren-style APIs expect a raw POST body or a specific form field
                // But the official 'apitoken' endpoint usually accepts a raw JSON body.
                // Since a standard form can't easily send a raw JSON body without being 'application/x-www-form-urlencoded',
                // we'll try a 'fetch' one more time with 'credentials: include' first, 
                // and if THAT fails, we use the FORM with a single JSON field or just let it fail.
                
                // RETHINK: If fetch failed, let's try fetch WITH 'credentials: include' and NO custom headers
                fetch("https://authapi.flattrade.in/trade/apitoken", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    credentials: "include", 
                    body: JSON.stringify(p)
                })
                .then(async response => {
                    const text = await response.text();
                    let data;
                    try { data = JSON.parse(text); } catch(e) { data = { stat: "Not Ok", emsg: "Raw: " + text.substring(0, 100) }; }
                    arguments[arguments.length - 1]({status: "success", data: data});
                })
                .catch(err => arguments[arguments.length - 1]({status: "error", message: err.toString()}));
                """
                
                try:
                    token_res = driver.execute_async_script(submit_js, creds['api_key'], request_code, hash_value)
                    
                    if token_res["status"] == "success":
                        data = token_res["data"]
                        if data.get("stat") == "Ok":
                            log("✅ In-Browser Bypass SUCCESSFUL!")
                            return {"status": "success", "code": request_code, "token": data["token"]}
                        else:
                            log(f"⚠️ Bypass API Error: {data.get('emsg', 'Unknown')}")
                    else:
                        log(f"⚠️ Bypass Script Error: {token_res.get('message', 'Unknown')}")
                except Exception as e:
                    log(f"⚠️ In-Browser Bypass failed: {e}")
            else:
                log(f"⚠️ Python Exchange failed: {res.get('message')}")
                
            return {"status": "error", "message": f"Token generation failed. Try Manual Injection."}
        else:
            # CAPTURE SCREENSHOT ON ALL REDIRECT FAILURES
            try:
                if not os.path.exists('logs'): os.makedirs('logs')
                sp = os.path.join('logs', f"login_fail_{int(time.time())}.png")
                driver.save_screenshot(sp)
                log(f"DEBUG: Screenshot captured at {sp}")
            except: pass

            # 1. Check for mandatory password change screen specifically
            if "Change password" in driver.page_source or "new password" in driver.page_source.lower():
                return {"status": "error", "message": "Mandatory Password Reset Required. Please log in manually once to update your password."}

            # 2. Check for other error messages on the page
            error_msg = "Failed to capture request_code from URL"
            try:
                # Check for standard snackbars or alerts
                alerts = driver.find_elements(By.XPATH, "//*[contains(@class, 'v-snack') or contains(@class, 'v-alert') or contains(@role, 'alert')]")
                for alert in alerts:
                    if alert.is_displayed() and alert.text:
                        error_msg = alert.text
                        break
            except:
                pass
            return {"status": "error", "message": f"Login failed: {error_msg}"}

    except Exception as e:
        log(f"Automation error: {e}")
        # Capture screenshot for debugging
        if driver:
            try:
                if not os.path.exists('logs'):
                    os.makedirs('logs')
                screenshot_path = os.path.join('logs', f"login_error_{int(time.time())}.png")
                driver.save_screenshot(screenshot_path)
                log(f"Screenshot saved to {screenshot_path}")
            except Exception as e2:
                log(f"Failed to save screenshot: {e2}")
        return {"status": "error", "message": str(e)}
    finally:
        if driver:
            driver.quit()

def generate_access_token(request_code, api_key=None, api_secret=None):
    # Use provided credentials or fallback to environment/file
    creds = {
        'api_key': api_key or os.environ.get('FT_API_KEY'),
        'api_secret': api_secret or os.environ.get('FT_API_SECRET')
    }
    
    # Secondary fallback to credentials.json if still missing
    if not all(creds.values()):
        if os.path.exists('credentials.json'):
            with open('credentials.json', 'r') as f:
                file_creds = json.load(f)
                creds['api_key'] = creds['api_key'] or file_creds.get('api_key')
                creds['api_secret'] = creds['api_secret'] or file_creds.get('api_secret')
        
    if not all(creds.values()):
        return {"status": "error", "message": "Missing API Key or API Secret for token generation."}

    token_url = "https://authapi.flattrade.in/trade/apitoken"
    # Logic: SHA256(api_key + request_code + api_secret)
    hash_payload = (creds['api_key'] + request_code + creds['api_secret']).encode()
    hash_value = hashlib.sha256(hash_payload).hexdigest()

    # Diagnostic: Log IP
    current_ip = get_outbound_ip()
    print(f"DIAGNOSTIC: Token request outbound IP: {current_ip}")

    payload = {
        "api_key": creds['api_key'],
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

    try:
        response = requests.post(token_url, json=payload, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("stat") == "Ok":
                return {"status": "success", "token": data["token"]}
            else:
                emsg = data.get('emsg', 'Unknown API Error')
                print(f"Error from Flattrade API: {emsg}")
                return {"status": "error", "message": emsg}
        else:
            return {"status": "error", "message": f"HTTP {response.status_code}: {response.text[:100]}"}
    except Exception as e:
        return {"status": "error", "message": f"Network error during token generation: {str(e)}"}

if __name__ == "__main__":
    result = auto_login()
    if result["status"] == "success":
        code = result["code"]
        res = generate_access_token(code)
        if res["status"] == "success":
            final_token = res["token"]
            print(f"SUCCESS! Access Token: {final_token}")
            # Save token for other scripts
            with open('flattrade_auth.json', 'w') as f:
                json.dump({"token": final_token}, f)
        else:
            print(f"Failed to generate access token: {res.get('message')}")
    else:
        print(f"Automation failed: {result.get('message')}")
