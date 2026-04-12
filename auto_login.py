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

def create_proxy_auth_extension(proxy_host, proxy_port, proxy_user, proxy_pass, scheme='socks5'):
    """Creates a temporary Chrome extension to handle proxy authentication."""
    import tempfile
    import zipfile
    
    plugin_path = os.path.join(tempfile.gettempdir(), f'proxy_auth_plugin_{int(time.time())}.zip')
    
    manifest_json = """
    {
        "version": "1.0.0",
        "manifest_version": 2,
        "name": "Chrome Proxy",
        "permissions": [
            "proxy", "tabs", "unlimitedStorage", "storage", "<all_urls>", "webRequest", "webRequestBlocking"
        ],
        "background": {
            "scripts": ["background.js"]
        },
        "minimum_chrome_version":"22.0.0"
    }
    """
    
    background_js = """
    var config = {
        mode: "fixed_servers",
        rules: {
            singleProxy: {
                scheme: "%s",
                host: "%s",
                port: parseInt(%s)
            },
            bypassList: []
        }
    };
    chrome.proxy.settings.set({value: config, scope: "regular"}, function() {});
    function callbackFn(details) {
        return {
            authCredentials: {
                username: "%s",
                password: "%s"
            }
        };
    }
    chrome.webRequest.onAuthRequired.addListener(
        callbackFn,
        {urls: ["<all_urls>"]},
        ['blocking']
    );
    """ % (scheme, proxy_host, proxy_port, proxy_user, proxy_pass)
    
    with zipfile.ZipFile(plugin_path, 'w') as zp:
        zp.writestr("manifest.json", manifest_json)
        zp.writestr("background.js", background_js)
    return plugin_path

def get_outbound_ip(proxies=None):
    """Diagnostic helper to see which IP Flattrade sees"""
    try:
        return requests.get("https://api.ipify.org", proxies=proxies, timeout=5).text
    except:
        return "Unknown"


def safe_get_secret(key, default=None):
    """Safely get a secret from streamlit secrets or environment variables."""
    try:
        import streamlit as st
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.environ.get(key, default)

def auto_login(creds=None, headless=False, log_func=None):
    def log(msg):
        print(msg)
        if log_func:
            log_func(msg)

    # Load credentials if not provided
    if creds is None:
        # Try secrets first (Cloud), then environment, then local file
        creds = {
            'username': safe_get_secret('FT_USERNAME'),
            'password': safe_get_secret('FT_PASSWORD'),
            'totp_key': safe_get_secret('FT_TOTP_KEY'),
            'api_key': safe_get_secret('FT_API_KEY'),
            'api_secret': safe_get_secret('FT_API_SECRET'),
            'proxy_host': safe_get_secret('FT_PROXY_HOST'),
            'proxy_port': safe_get_secret('FT_PROXY_PORT', '1080'),
            'proxy_user': safe_get_secret('FT_PROXY_USER'),
            'proxy_pass': safe_get_secret('FT_PROXY_PASS'),
            'use_proxy': str(safe_get_secret('FT_USE_PROXY', 'false')).lower() == 'true'
        }
        
        # Check if login credentials are found in environment
        if not all([creds['username'], creds['password'], creds['totp_key'], creds['api_key'], creds['api_secret']]):
            print("Login credentials missing in environment, checking credentials.json...")
            if os.path.exists('credentials.json'):
                with open('credentials.json', 'r') as f:
                    file_creds = json.load(f)
                    # Use file values for only missing ones
                    for key in creds:
                        if key in file_creds and not (isinstance(creds[key], str) and creds[key]):
                            if key == 'use_proxy':
                                creds[key] = str(file_creds.get(key, 'false')).lower() == 'true'
                            else:
                                creds[key] = file_creds.get(key)
            else:
                print("Error: credentials.json not found and essential environment variables missing.")
                return {"status": "error", "message": "Missing essential credentials"}

    # Generate TOTP
    if not creds.get('totp_key'):
        log("Error: Missing TOTP key in credentials.")
        return {"status": "error", "message": "Missing TOTP key"}
        
    totp = pyotp.TOTP(creds['totp_key'])
    token = totp.now()
    log(f"Generated TOTP: {token}")

    # Setup Selenium via undetected_chromedriver
    chrome_options = uc.ChromeOptions()
    
    # Absolute Session Isolation: Always use a fresh, unique profile to prevent FTACKM04 session conflicts
    import tempfile
    user_data_dir = os.path.join(tempfile.gettempdir(), f'chrome_profile_{int(time.time())}')
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
        
    # Proxy Configuration
    proxies = None
    if creds.get('use_proxy') and creds.get('proxy_host'):
        proxy_host = creds.get('proxy_host')
        proxy_port = creds.get('proxy_port', '1080')
        proxy_user = creds.get('proxy_user', '')
        proxy_pass = creds.get('proxy_pass', '')
        
        log(f"Configuring SOCKS5 Proxy: {proxy_host}:{proxy_port}")
        
        if proxy_user and proxy_pass:
            proxy_url = f"socks5h://{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}"
            # For Selenium with Auth, we use the extension bypass
            ext_path = create_proxy_auth_extension(proxy_host, proxy_port, proxy_user, proxy_pass)
            chrome_options.add_extension(ext_path)
            # IMPORTANT: For UC to work with extensions, we might need to adjust some settings
            # and --proxy-server argument might conflict with extension in some cases
        else:
            proxy_url = f"socks5h://{proxy_host}:{proxy_port}"
            chrome_options.add_argument(f"--proxy-server=socks5://{proxy_host}:{proxy_port}")
            
        proxies = {"http": proxy_url, "https": proxy_url}
        log(f"Requests proxy configured: {proxy_url.split('@')[-1] if '@' in proxy_url else proxy_url}")

    # Diagnostic: Check IP before starting Selenium
    current_ip = get_outbound_ip(proxies=proxies)
    log(f"Outbound IP Detection: {current_ip}")
        
    driver = None
    try:
        # Navigate to login page
        auth_url = f"https://auth.flattrade.in/?app_key={creds['api_key']}"
        
        try:
            # Try undetected_chromedriver first (works best for local/Windows)
            # Detect browser version to avoid version mismatch errors
            version_main = None
            try:
                import subprocess
                if os.name == 'nt':
                    cmd = r'reg query "HKEY_CURRENT_USER\Software\Google\Chrome\BLBeacon" /v version'
                    output = subprocess.check_output(cmd, shell=True).decode()
                    version_main = int(output.strip().split()[-1].split('.')[0])
                    log(f"Detected local Chrome version: {version_main}")
            except:
                pass

            linux_chrome_path = None
            if os.name != 'nt':
                # Common paths for Chrome/Chromium on Linux runners
                potential_paths = [
                    '/usr/bin/google-chrome-stable',
                    '/usr/bin/google-chrome',
                    '/usr/bin/chromium',
                    '/usr/bin/chromium-browser'
                ]
                for p in potential_paths:
                    if os.path.exists(p):
                        linux_chrome_path = p
                        # Try to detect version from the binary itself on Linux
                        try:
                            v_out = subprocess.check_output([linux_chrome_path, '--version']).decode()
                            version_main = int(v_out.strip().split()[-1].split('.')[0])
                            log(f"Detected Linux Chrome version: {version_main} at {linux_chrome_path}")
                        except: pass
                        break
            
            if linux_chrome_path:
                chrome_options.binary_location = linux_chrome_path
                driver = uc.Chrome(options=chrome_options, browser_executable_path=linux_chrome_path, use_subprocess=True, version_main=version_main)
            else:
                # Fallback for Windows or default search
                driver = uc.Chrome(options=chrome_options, use_subprocess=True, version_main=version_main)
        except Exception as e:
            log(f"Undetected ChromeDriver setup failed: {e}")
            log("Attempting fallback to 'Stealthy' Standard Selenium WebDriver...")
            try:
                from selenium.webdriver.chrome.service import Service
                from webdriver_manager.chrome import ChromeDriverManager
                
                std_options = webdriver.ChromeOptions()
                # Essential stealth for standard fallback
                std_options.add_argument("--disable-blink-features=AutomationControlled")
                std_options.add_experimental_option("excludeSwitches", ["enable-automation"])
                std_options.add_experimental_option('useAutomationExtension', False)
                
                for arg in chrome_options.arguments:
                    if "headless" in arg or "no-sandbox" in arg or "disable-gpu" in arg:
                        std_options.add_argument(arg)
                
                if os.name != 'nt':
                    std_options.binary_location = '/usr/bin/chromium' if os.path.exists('/usr/bin/chromium') else '/usr/bin/google-chrome'
                    service = Service('/usr/bin/chromedriver') if os.path.exists('/usr/bin/chromedriver') else Service(ChromeDriverManager().install())
                else:
                    service = Service(ChromeDriverManager().install())
                    
                driver = webdriver.Chrome(service=service, options=std_options)
                
                # Spoof navigator.webdriver
                driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                    "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                })
                log("Standard Selenium WebDriver launched with hardened stealth.")
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
                log("⚠️ Python Exchange failed with INVALID_IP. Attempting 'Same-Origin' Bypass...")
                
                hash_payload = (creds['api_key'] + request_code + creds['api_secret']).encode()
                hash_value = hashlib.sha256(hash_payload).hexdigest()
                
                # Navigate to the API's own subdomain to make it a 'Same-Origin' request
                # Same-origin requests bypass CORS completely!
                # Navigate to the API domain directly to establish trust for Same-Origin requests
                # This bypasses CORS because the fetch will be same-domain.
                api_trust_url = "https://authapi.flattrade.in/trade/apitoken"
                log(f"Establishing Same-Origin trust via {api_trust_url}...")
                driver.get(api_trust_url) # This may show a method not allowed error, which is fine
                time.sleep(2)
                
                exchange_js = """
                var callback = arguments[arguments.length - 1];
                var payload = {
                    "api_key": arguments[0],
                    "request_code": arguments[1],
                    "api_secret": arguments[2]
                };
                
                console.log("Attempting Same-Origin Token Exchange...");
                
                fetch("/trade/apitoken", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                })
                .then(async response => {
                    const status = response.status;
                    const text = await response.text();
                    console.log("Response Status:", status);
                    console.log("Response Text:", text);
                    
                    try { 
                        const data = JSON.parse(text); 
                        callback({status: "success", data: data});
                    } catch(e) { 
                        callback({status: "error", message: "Failed to parse JSON: " + text.substring(0, 100)});
                    }
                })
                .catch(err => {
                    console.error("Fetch Error:", err);
                    callback({status: "error", message: err.toString()});
                });
                """
                
                try:
                    token_res = driver.execute_async_script(exchange_js, creds['api_key'], request_code, hash_value)
                    
                    if token_res["status"] == "success":
                        data = token_res["data"]
                        if data.get("stat") == "Ok":
                            log("✅ 'Same-Origin' Bypass SUCCESSFUL!")
                            return {"status": "success", "code": request_code, "token": data["token"]}
                        else:
                            log(f"⚠️ Bypass API Error: {data.get('emsg', 'Unknown')}")
                    else:
                        log(f"⚠️ Bypass Script Error: {token_res.get('message', 'Unknown')}")
                except Exception as e:
                    log(f"⚠️ Same-Origin Bypass failed during execution: {e}")
            else:
                log(f"⚠️ Python Exchange failed: {res.get('message')}")
                
            return {"status": "error", "message": f"Token generation failed. Try Manual Injection or GitHub Action."}
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
    creds_to_use = {
        'api_key': api_key or os.environ.get('FT_API_KEY'),
        'api_secret': api_secret or os.environ.get('FT_API_SECRET')
    }
    
    # Load full creds for proxy check
    proxy_creds = {}
    if os.path.exists('credentials.json'):
        with open('credentials.json', 'r') as f:
            proxy_creds = json.load(f)
            creds_to_use['api_key'] = creds_to_use['api_key'] or proxy_creds.get('api_key')
            creds_to_use['api_secret'] = creds_to_use['api_secret'] or proxy_creds.get('api_secret')
        
    if not all(creds_to_use.values()):
        return {"status": "error", "message": "Missing API Key or API Secret for token generation."}

    # Proxy Configuration for Token Exchange
    proxies = None
    if proxy_creds.get('use_proxy') and proxy_creds.get('proxy_host'):
        p_host = proxy_creds.get('proxy_host')
        p_port = proxy_creds.get('proxy_port', '1080')
        p_user = proxy_creds.get('proxy_user', '')
        p_pass = proxy_creds.get('proxy_pass', '')
        if p_user and p_pass:
            p_url = f"socks5h://{p_user}:{p_pass}@{p_host}:{p_port}"
        else:
            p_url = f"socks5h://{p_host}:{p_port}"
        proxies = {"http": p_url, "https": p_url}

    token_url = "https://authapi.flattrade.in/trade/apitoken"
    # Logic: SHA256(api_key + request_code + api_secret)
    hash_payload = (creds_to_use['api_key'] + request_code + creds_to_use['api_secret']).encode()
    hash_value = hashlib.sha256(hash_payload).hexdigest()

    # Diagnostic: Log IP
    current_ip = get_outbound_ip(proxies=proxies)
    print(f"DIAGNOSTIC: Token request outbound IP: {current_ip}")

    payload = {
        "api_key": creds_to_use['api_key'],
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
        response = requests.post(token_url, json=payload, headers=headers, proxies=proxies, timeout=10)
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
