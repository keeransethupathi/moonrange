import time
import json
import pyotp
import os
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import requests
import hashlib

def auto_login(creds=None, headless=False):
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
    totp = pyotp.TOTP(creds['totp_key'])
    token = totp.now()
    print(f"Generated TOTP: {token}")

    # Setup Selenium
    chrome_options = Options()
    if headless:
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        
    driver = None
    try:
        # Navigate to login page
        auth_url = f"https://auth.flattrade.in/?app_key={creds['api_key']}"
        
        # Setup Selenium with better error handling for cloud environments
        chrome_options = Options()
        if headless:
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")

        try:
            # First try standard ChromeDriverManager
            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
        except Exception as e:
            print(f"Standard ChromeDriver failed, trying system chromium: {e}")
            # Fallback for Streamlit Cloud (Linux)
            try:
                chrome_options.binary_location = "/usr/bin/chromium"
                service = Service("/usr/bin/chromedriver")
                driver = webdriver.Chrome(service=service, options=chrome_options)
            except Exception as e2:
                print(f"System chromium failed: {e2}")
                # Last ditch effort: try without service path
                chrome_options.binary_location = "/usr/bin/chromium-browser"
                driver = webdriver.Chrome(options=chrome_options)

        driver.get(auth_url)
        print(f"Navigated to login page: {auth_url.split('=')[0]}=...")
        time.sleep(3) # Give page more time to settle on cloud environments

        # Helper for resilient input
        def send_keys_resilient(xpath_list, value, label):
            if not value:
                print(f"Error: No value provided for {label}")
                return False
            for xpath in xpath_list:
                for attempt in range(3):
                    try:
                        element = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
                        wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
                        
                        # Human-like interaction: Click -> Clear -> Type Char-by-char -> Blur
                        driver.execute_script("arguments[0].click();", element)
                        time.sleep(0.2)
                        element.clear()
                        
                        for char in value:
                            element.send_keys(char)
                            time.sleep(0.05) if headless else time.sleep(0.02)
                        
                        # Force update via JavaScript and events (Crucial for Vue/React)
                        js_script = """
                        var element = arguments[0];
                        var val = arguments[1];
                        element.value = val;
                        // Dispatch multiple events to ensure framework detection
                        element.dispatchEvent(new Event('input', { bubbles: true }));
                        element.dispatchEvent(new Event('change', { bubbles: true }));
                        element.dispatchEvent(new Event('blur', { bubbles: true }));
                        """
                        driver.execute_script(js_script, element, value)
                        
                        # Verify the value stuck
                        current_val = element.get_attribute('value')
                        if current_val == value:
                            print(f"Entered and verified {label} using {xpath}")
                            return True
                        else:
                            print(f"Value verification failed for {label}: expected {value}, got {current_val}")
                    except Exception as ex:
                        print(f"Attempt {attempt+1} fail for {label} ({xpath}): {ex}")
                        time.sleep(1)
            return False

        # Wait for and fill username
        wait = WebDriverWait(driver, 15)
        
        # Possible User ID selectors
        user_xpaths = ["//input[@placeholder='User ID']", "//input[@placeholder='Username']", "//input[@name='user_id']"]
        if not send_keys_resilient(user_xpaths, creds['username'], "username"):
            return {"status": "error", "message": "Failed to find username input"}

        # Fill password
        pass_xpaths = ["//input[@placeholder='Password']", "//input[@name='password']"]
        if not send_keys_resilient(pass_xpaths, creds['password'], "password"):
            return {"status": "error", "message": "Failed to find password input"}

        # Fill TOTP
        totp_xpaths = ["//input[@placeholder='OTP / TOTP']", "//input[@placeholder='TOTP']", "//input[@name='otp']"]
        if not send_keys_resilient(totp_xpaths, token, "TOTP"):
            return {"status": "error", "message": "Failed to find TOTP input"}

        # Click Login
        print("Clicking login button...")
        time.sleep(1)
        
        try:
            # Use JavaScript for a robust click
            script = """
            var buttons = document.querySelectorAll('button');
            for (var i = 0; i < buttons.length; i++) {
                var text = buttons[i].textContent.toLowerCase();
                if (text.includes('log in') || text.includes('submit') || text.includes('authorize')) {
                    buttons[i].click();
                    return true;
                }
            }
            return false;
            """
            for attempt in range(3):
                clicked = driver.execute_script(script)
                if clicked:
                    print(f"Clicked login button via JS (attempt {attempt+1})")
                    break
                else:
                    # Fallback to standard wait if JS fails 
                    try:
                        login_btn = driver.find_element(By.XPATH, "//button[contains(translate(., 'LOGIN', 'login'), 'login')]")
                        driver.execute_script("arguments[0].click();", login_btn)
                        print("Clicked login button via backup XPath")
                        break
                    except:
                        pass
                time.sleep(1)
        except Exception as e:
            print(f"Login click failed: {e}")

        # Wait for redirect and capture code
        print("Waiting for redirect and handling potential modals...")
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
                        print("Detected 'Confirm Password Change' modal. Clicking CONFIRM...")
                        d.execute_script("arguments[0].click();", confirm_btn[0])
                        # After clicking, we continue waiting for the redirect
                        return False 
                except:
                    pass
                
                # 3. Check for mandatory password change screen
                try:
                    if "Change password" in d.page_source or "new password" in d.page_source.lower():
                        print("Detected mandatory password change screen.")
                        return True
                except:
                    pass

                # 4. Check for specific error messages on page
                if "error" in d.current_url.lower():
                    return True
                    
                return False

            WebDriverWait(driver, 30).until(wait_for_login_result)
        except Exception as we:
            print(f"Wait for redirect/modal finished or timed out: {we}")
            
        current_url = driver.current_url
        print(f"Current URL: {current_url}")

        if 'code=' in current_url:
            request_code = current_url.split('code=')[1].split('&')[0]
            print(f"Captured request_code: {request_code}")
            return {"status": "success", "code": request_code}
        else:
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
        print(f"Automation error: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        driver.quit()

def generate_access_token(request_code):
    # Try environment variables first
    creds = {
        'api_key': os.environ.get('FT_API_KEY'),
        'api_secret': os.environ.get('FT_API_SECRET')
    }
    
    if not all(creds.values()):
        if os.path.exists('credentials.json'):
            with open('credentials.json', 'r') as f:
                file_creds = json.load(f)
                creds['api_key'] = creds['api_key'] or file_creds.get('api_key')
                creds['api_secret'] = creds['api_secret'] or file_creds.get('api_secret')
        else:
            print("Error: credentials.json not found for token generation.")
            return None

    token_url = "https://authapi.flattrade.in/trade/apitoken"
    hash_value = hashlib.sha256((creds['api_key'] + request_code + creds['api_secret']).encode()).hexdigest()

    payload = {
        "api_key": creds['api_key'],
        "request_code": request_code,
        "api_secret": hash_value
    }

    response = requests.post(token_url, json=payload)
    if response.status_code == 200:
        data = response.json()
        if data.get("stat") == "Ok":
            return data["token"]
        else:
            print(f"Error in token generation: {data.get('emsg')}")
    return None

if __name__ == "__main__":
    result = auto_login()
    if result["status"] == "success":
        code = result["code"]
        final_token = generate_access_token(code)
        if final_token:
            print(f"SUCCESS! Access Token: {final_token}")
            # Save token for other scripts
            with open('flattrade_auth.json', 'w') as f:
                json.dump({"token": final_token}, f)
        else:
            print("Failed to generate access token from code.")
    else:
        print(f"Automation failed: {result.get('message')}")
