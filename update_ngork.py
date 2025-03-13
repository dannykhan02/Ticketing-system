import os
import requests
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

NGROK_API_URL = "http://127.0.0.1:4040/api/tunnels"
ENV_FILE = ".env"

def update_ngrok_urls():
    try:
        # Get the current Ngrok URL
        response = requests.get(NGROK_API_URL)
        tunnels = response.json().get("tunnels", [])
        public_url = next((t["public_url"] for t in tunnels if t["proto"] == "https"), None)

        if public_url:
            # Update .env file
            with open(ENV_FILE, "r") as file:
                lines = file.readlines()

            with open(ENV_FILE, "w") as file:
                updated = False
                for line in lines:
                    if line.startswith("PAYSTACK_CALLBACK_URL="):
                        file.write(f"PAYSTACK_CALLBACK_URL={public_url}/paystack/callback\n")
                        updated = True
                    elif line.startswith("CALLBACK_URL="):
                        file.write(f"CALLBACK_URL={public_url}/stk\n")
                        updated = True
                    else:
                        file.write(line)

                # Add the callback URLs if they don't exist
                if not any(line.startswith("PAYSTACK_CALLBACK_URL=") for line in lines):
                    file.write(f"PAYSTACK_CALLBACK_URL={public_url}/paystack/callback\n")
                    updated = True
                if not any(line.startswith("CALLBACK_URL=") for line in lines):
                    file.write(f"CALLBACK_URL={public_url}/stk\n")
                    updated = True

            if updated:
                print(f"✅ Updated .env with Ngrok URL:\n  - Paystack: {public_url}/paystack/callback\n  - M-Pesa: {public_url}/stk")
            else:
                print("✅ .env file is already up to date.")

    except Exception as e:
        print(f"❌ Error updating Ngrok URL: {e}")

if __name__ == "__main__":
    update_ngrok_urls()
