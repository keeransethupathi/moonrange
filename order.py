import requests
import json
import os

def place_flattrade_order(tsym, qty, exch, trantype):
    """
    Places an order on Flattrade.
    tsym: Trading Symbol
    qty: Quantity
    exch: Exchange
    trantype: 'B' for Buy, 'S' for Sell
    """
    base_url = "https://piconnect.flattrade.in/PiConnectAPI"
    order_url = f"{base_url}/PlaceOrder"
    search_url = f"{base_url}/SearchScrip"
    quote_url = f"{base_url}/GetQuotes"

    # Load jkey and credentials
    try:
        with open('flattrade_auth.json', 'r') as f:
            auth_data = json.load(f)
            jkey = auth_data.get('token')
            if not jkey:
                return {"stat": "Not Ok", "emsg": "Token not found"}
        
        uid = os.environ.get('FT_USERNAME')
        if not uid:
            if os.path.exists('credentials.json'):
                with open('credentials.json', 'r') as f:
                    uid = json.load(f).get('username')
            
        if not uid:
            return {"stat": "Not Ok", "emsg": "User ID not found"}
    except Exception as e:
        return {"stat": "Not Ok", "emsg": f"Auth error: {str(e)}"}

    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    # 1. Flattrade API V2 rejects MKT (Market) orders.
    # We must use LMT (Limit). To simulate Market, we fetch the LTP and add a buffer.
    try:
        # Search for Token
        search_payload = 'jData=' + json.dumps({"uid": uid, "exch": exch, "stext": tsym}) + '&jKey=' + jkey
        s_res = requests.post(search_url, data=search_payload, headers=headers).json()
        
        if s_res.get("stat") != "Ok" or not s_res.get("values"):
            return {"stat": "Not Ok", "emsg": f"Symbol '{tsym}' not found or expired!"}
            
        # Get exact token
        token = s_res["values"][0]["token"]
        for item in s_res["values"]:
            if item.get("tsym") == tsym:
                token = item["token"]
                break
                
        # Get Option LTP
        quote_payload = 'jData=' + json.dumps({"uid": uid, "exch": exch, "token": token}) + '&jKey=' + jkey
        q_res = requests.post(quote_url, data=quote_payload, headers=headers).json()
        if q_res.get("stat") != "Ok":
            return {"stat": "Not Ok", "emsg": f"Failed to get price for {tsym}"}
            
        ltp = float(q_res.get("lp", 0))
        if ltp <= 0:
            return {"stat": "Not Ok", "emsg": f"Invalid Price for {tsym}"}
            
        # Simulate Market Order using Limit with 3% buffer
        if trantype == 'B':
            limit_price = ltp * 1.03
        else:
            limit_price = max(0.05, ltp * 0.97)
            
        # Tick size rounding (Nearest 0.05)
        limit_price = round(limit_price / 0.05) * 0.05
        
    except Exception as e:
        return {"stat": "Not Ok", "emsg": f"Price sync error: {e}"}

    order_data = {
        "uid": uid,
        "actid": uid,
        "exch": exch,
        "tsym": tsym,
        "qty": str(qty),
        "prd": "M",
        "trantype": trantype,
        "prctyp": "LMT",
        "prc": f"{limit_price:.2f}",
        "blprc": "0",
        "ret": "DAY",
        "amo": "NO",
        "ordersource": "API",
        "remarks": "OrderPortal"
    }

    jdata_compact = json.dumps(order_data, separators=(",", ":"))
    body = f"jData={jdata_compact}&jKey={jkey}"

    try:
        response = requests.post(order_url, data=body, headers=headers)
        if response.status_code == 200:
            return response.json()
        else:
            return {
                "stat": "Not Ok", 
                "emsg": f"HTTP {response.status_code}: {response.text[:100]}"
            }
    except Exception as e:
        return {"stat": "Not Ok", "emsg": str(e)}

if __name__ == "__main__":
    print("Testing order placement...")
