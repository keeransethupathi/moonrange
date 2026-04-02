from NorenRestApiPy.NorenApi import NorenApi
import time, socket

old_getaddrinfo = socket.getaddrinfo
def new_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return old_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = new_getaddrinfo

api = NorenApi(host='https://piconnect.flattrade.in/PiConnectAPI/', websocket='wss://piconnect.flattrade.in/NorenWS/')
api.set_session(userid='FZ23457', password='old_password', usertoken='d4773dc026b67c0fde58db4328e3d777f38f71208fb03ccf8d8c62266915a0bf')

def on_open():
    print("WS Connected via NorenApi")
def on_error(msg):
    print(f"WS Error via NorenApi: {msg}")
def on_close():
    print("WS Closed via NorenApi")

api.start_websocket(socket_open_callback=on_open, socket_error_callback=on_error, socket_close_callback=on_close)

time.sleep(5)
api.close_websocket()
