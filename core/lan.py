"""Утаснаас (iPhone / Android) Wi-Fi-аар холбогдох: тусдаа порт дээр 0.0.0.0-д сонсох сервер, PIN/токен хамгаалалт."""
import hmac
import io
import secrets
import socket
import threading

from . import store

state = {"running": False, "port": None, "error": ""}
_srv = None
_lock = threading.Lock()


def ensure_secrets():
    s = store.load("settings")
    changed = False
    if not s.get("lan_pin"):
        s["lan_pin"] = f"{secrets.randbelow(1000000):06d}"
        changed = True
    if not s.get("lan_token"):
        s["lan_token"] = secrets.token_urlsafe(24)
        changed = True
    if changed:
        store.save("settings", s)
    return s


def regenerate():
    s = store.load("settings")
    s["lan_pin"] = f"{secrets.randbelow(1000000):06d}"
    s["lan_token"] = secrets.token_urlsafe(24)
    store.save("settings", s)
    return s


def check_token(tok):
    s = store.load("settings")
    return bool(tok) and bool(s.get("lan_token")) and hmac.compare_digest(str(tok), s["lan_token"])


def check_pin(pin):
    s = store.load("settings")
    return bool(pin) and bool(s.get("lan_pin")) and hmac.compare_digest(str(pin).strip(), s["lan_pin"])


def local_ips():
    """Энэ компьютерийн дотоод сүлжээний IP хаягууд (192.168.x.x гэх мэт)."""
    ips = []
    try:  # гарах интерфэйсийн IP (пакет илгээгдэхгүй)
        so = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        so.connect(("10.255.255.255", 1))
        ips.append(so.getsockname()[0])
        so.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.append(info[4][0])
    except OSError:
        pass
    out = []
    for ip in ips:
        if ip and not ip.startswith(("127.", "169.254.")) and ip not in out:
            out.append(ip)
    # хувийн сүлжээний хаягууд эхэнд
    out.sort(key=lambda ip: 0 if ip.startswith(("192.168.", "10.")) else 1 if ip.startswith("172.") else 2)
    return out


def urls():
    s = store.load("settings")
    port = state["port"] or int(s.get("lan_port") or 4569)
    return [f"http://{ip}:{port}" for ip in local_ips()]


def qr_svg(text):
    try:
        import segno
    except ImportError:
        return ""
    b = io.BytesIO()
    segno.make(text, error="m").save(b, kind="svg", scale=5, dark="#04222b", light="#ffffff", border=3)
    return b.getvalue().decode()


def start(app):
    global _srv
    from werkzeug.serving import make_server
    with _lock:
        if _srv:
            return
        ensure_secrets()
        port = int(store.load("settings").get("lan_port") or 4569)
        try:
            srv = make_server("0.0.0.0", port, app, threaded=True)
        except OSError as e:
            state.update(running=False, port=None, error=f"{port} порт ашиглагдаж байна ({e})")
            return
        _srv = srv
        state.update(running=True, port=port, error="")
    threading.Thread(target=srv.serve_forever, daemon=True).start()


def stop():
    global _srv
    with _lock:
        srv, _srv = _srv, None
        state.update(running=False, port=None)
    if srv:
        try:
            srv.shutdown()
            srv.server_close()
        except Exception:
            pass
