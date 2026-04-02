import websocket, json, time, socket

old_getaddrinfo = socket.getaddrinfo
def new_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return old_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = new_getaddrinfo

uid = "FZ23457"
token = "d4773dc026b67c0fde58db4328e3d777f38f71208fb03ccf8d8c62266915a0bf"

urls = [
    "wss://authapi.flattrade.in/NorenWSTP/",
    "wss://authapi.flattrade.in/NorenWS/",
    "wss://piconnect.flattrade.in/PiConnectWSTP/",
    "wss://piconnect.flattrade.in/NorenWSTP/",
]

for url in urls:
    print(f"Testing {url}")
    try:
        ws = websocket.create_connection(url, timeout=3)
        ws.send(json.dumps({
            "t": "c",
            "uid": uid,
            "actid": uid,
            "source": "API",
            "susertoken": token
        }))
        res = ws.recv()
        print(f"Result: {res}")
        ws.close()
    except Exception as e:
        print(f"Error: {e}")
