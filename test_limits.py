import json, requests

AUTH_FILE = "flattrade_auth.json"
with open(AUTH_FILE, "r") as f:
    auth_data = json.load(f)
token = auth_data.get("token")

url = "https://piconnect.flattrade.in/PiConnectAPI/Limits"
values = {"uid": "FZ23457", "actid": "FZ23457"}
payload = 'jData=' + json.dumps(values) + '&jKey=' + token
res = requests.post(url, data=payload)
print("Limits:", res.text)
