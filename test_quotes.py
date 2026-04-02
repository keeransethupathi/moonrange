import json, requests

AUTH_FILE = "flattrade_auth.json"
with open(AUTH_FILE, "r") as f:
    auth_data = json.load(f)
token = auth_data.get("token")

url = "https://piconnect.flattrade.in/PiConnectAPI/GetQuotes"
values = {"uid": "FZ23457", "exch": "NSE", "token": "26000"}
payload = 'jData=' + json.dumps(values) + '&jKey=' + token
res = requests.post(url, data=payload)
print("Quotes NSE|26000:", res.text)

values = {"uid": "FZ23457", "exch": "BSE", "token": "1"}
payload = 'jData=' + json.dumps(values) + '&jKey=' + token
res = requests.post(url, data=payload)
print("Quotes BSE|1:", res.text)
