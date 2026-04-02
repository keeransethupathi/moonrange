import os
import json
import logging
from auto_login import auto_login

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    # Read credentials from environment variables (for GitHub Secrets)
    creds = {
        "username": os.environ.get("FT_USERNAME"),
        "password": os.environ.get("FT_PASSWORD"),
        "totp_key": os.environ.get("FT_TOTP_SECRET"),
        "api_key": os.environ.get("FT_API_KEY"),
        "api_secret": os.environ.get("FT_API_SECRET")
    }

    # Validate missing credentials
    missing = [k for k, v in creds.items() if not v]
    if missing:
        logger.error(f"Missing required environment variables: {', '.join(missing)}")
        return

    logger.info(f"Starting Headless Login for user: {creds['username']}...")
    
    # Run the automation in headless mode
    result = auto_login(creds=creds, headless=True, log_func=logger.info)

    if result.get("status") == "success":
        token = result.get("token")
        if token:
            auth_data = {
                "api_key": creds["api_key"],
                "token": token,
                "generated_at": os.getenv("GITHUB_RUN_ID", "local")
            }
            with open("flattrade_auth.json", "w") as f:
                json.dump(auth_data, f, indent=4)
            logger.info("✅ Authentication successful. Token saved to flattrade_auth.json")
        else:
            logger.error("❌ Login successful but no token was captured.")
    else:
        logger.error(f"❌ Login failed: {result.get('message')}")
        exit(1)

if __name__ == "__main__":
    main()
