"""
bot_cdp.py — Minimal Chrome DevTools Protocol (CDP) client using ONLY the Python
stdlib (socket, base64, hashlib, struct, http.client, json). No pip installs.

Provides:
  - launch_chrome(url, port)        -> subprocess.Popen (headless Chrome)
  - discover_page_ws(port)          -> the page target's webSocketDebuggerUrl
  - CDP(ws_url)                     -> a tiny synchronous CDP client
      .send(method, params)         -> result dict (blocks until matching id)
      .evaluate(js, return_by_value)-> Runtime.evaluate wrapper -> python value
      .screenshot(path)             -> Page.captureScreenshot -> writes PNG
      .close()

The WebSocket client speaks RFC 6455 client frames well enough for CDP:
text frames out (masked), text/binary frames in (unmasked from server). It
handles fragmentation and ping/pong. CDP messages are small JSON, so this is
more than adequate.

This is a TEST HARNESS. It does not touch game code.
"""
import base64
import hashlib
import http.client
import json
import os
import socket
import struct
import subprocess
import time

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


# --------------------------------------------------------------------------
# Chrome launch + target discovery
# --------------------------------------------------------------------------
def launch_chrome(url, port=9222, user_data_dir=None, headless=True):
    """Launch a throwaway headless Chrome with remote debugging enabled.

    Uses a FRESH per-port user-data-dir so this bot's Chrome never collides with
    the user's own Chrome or a stale bot instance on the same machine."""
    if user_data_dir is None:
        # unique per port+pid so parallel/sequential runs never share a profile
        user_data_dir = os.path.join(
            os.environ.get("TEMP", "."), f"bot_chrome_{port}_{os.getpid()}")
    args = [
        CHROME,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-gpu",
        "--window-size=1280,860",
        "--hide-scrollbars",
        "--mute-audio",
    ]
    if headless:
        args.append("--headless=new")
    args.append(url)
    # DETACHED so it never grabs the user's focus; stderr/stdout to devnull.
    return subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _http_json(port, path):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return json.loads(data.decode("utf-8"))


def discover_page_ws(port=9222, timeout=25.0):
    """Poll the DevTools /json endpoint until a 'page' target with a ws URL appears."""
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            targets = _http_json(port, "/json")
            for t in targets:
                if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                    return t["webSocketDebuggerUrl"]
        except Exception as e:  # noqa: BLE001
            last_err = e
        time.sleep(0.4)
    raise RuntimeError(f"No page target with ws URL after {timeout}s (last err: {last_err})")


# --------------------------------------------------------------------------
# Minimal RFC 6455 WebSocket client (client side)
# --------------------------------------------------------------------------
class _WS:
    GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def __init__(self, ws_url, timeout=30.0):
        # ws_url like ws://127.0.0.1:9222/devtools/page/<ID>
        assert ws_url.startswith("ws://")
        rest = ws_url[len("ws://"):]
        hostport, _, path = rest.partition("/")
        host, _, port = hostport.partition(":")
        port = int(port or 80)
        path = "/" + path
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(handshake.encode())
        resp = self._read_until(b"\r\n\r\n")
        if b"101" not in resp.split(b"\r\n", 1)[0]:
            raise RuntimeError(f"WebSocket handshake failed: {resp[:120]!r}")
        accept = base64.b64encode(
            hashlib.sha1((key + self.GUID).encode()).digest()
        ).decode()
        if accept.encode() not in resp:
            raise RuntimeError("WebSocket handshake: bad Sec-WebSocket-Accept")
        self._buf = b""

    def _read_until(self, marker):
        data = b""
        while marker not in data:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            data += chunk
        return data

    def _recv_exact(self, n):
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("socket closed")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def send_text(self, text):
        payload = text.encode("utf-8")
        header = bytearray()
        header.append(0x81)  # FIN + text opcode
        mask = os.urandom(4)
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def recv_message(self):
        """Return a full application message (str), reassembling fragments."""
        chunks = []
        while True:
            b0 = self._recv_exact(1)[0]
            fin = b0 & 0x80
            opcode = b0 & 0x0F
            b1 = self._recv_exact(1)[0]
            masked = b1 & 0x80
            length = b1 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._recv_exact(8))[0]
            mask = self._recv_exact(4) if masked else b""
            data = self._recv_exact(length) if length else b""
            if masked:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if opcode == 0x9:  # ping -> pong
                self._send_control(0xA, data)
                continue
            if opcode == 0x8:  # close
                raise ConnectionError("server sent close frame")
            if opcode == 0xA:  # pong
                continue
            chunks.append(data)
            if fin:
                break
        return b"".join(chunks).decode("utf-8", "replace")

    def _send_control(self, opcode, data=b""):
        header = bytearray([0x80 | opcode])
        mask = os.urandom(4)
        header.append(0x80 | len(data))
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self.sock.sendall(bytes(header) + masked)

    def close(self):
        try:
            self._send_control(0x8)
        except Exception:  # noqa: BLE001
            pass
        try:
            self.sock.close()
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------------
# CDP wrapper
# --------------------------------------------------------------------------
class CDP:
    def __init__(self, ws_url, timeout=30.0):
        self._ws_url = ws_url
        self._timeout = timeout
        self.ws = _WS(ws_url, timeout=timeout)
        self._id = 0
        self._page_enabled = False

    def reconnect(self):
        """Re-open the WebSocket to the same target after a transient drop.
        DevTools keeps the target alive across websocket resets, so a fresh
        socket lands back on the same page with state intact."""
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001
            pass
        self.ws = _WS(self._ws_url, timeout=self._timeout)
        if self._page_enabled:
            # re-enable domains on the new socket (best-effort)
            for m in ("Page.enable", "Runtime.enable"):
                self._raw_send(m)

    def _raw_send(self, method, params=None):
        self._id += 1
        msg_id = self._id
        self.ws.send_text(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        while True:
            raw = self.ws.recv_message()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == msg_id:
                if "error" in msg:
                    raise RuntimeError(f"CDP {method} error: {msg['error']}")
                return msg.get("result", {})

    def send(self, method, params=None, _retry=True):
        try:
            return self._raw_send(method, params)
        except (ConnectionError, OSError) as e:
            if not _retry:
                raise
            # one transparent reconnect + retry on a transient transport drop
            try:
                self.reconnect()
            except Exception:  # noqa: BLE001
                raise e
            return self._raw_send(method, params)

    def evaluate(self, js, return_by_value=True, await_promise=False):
        res = self.send(
            "Runtime.evaluate",
            {"expression": js, "returnByValue": return_by_value,
             "awaitPromise": await_promise},
        )
        if "exceptionDetails" in res:
            raise RuntimeError(f"JS exception: {res['exceptionDetails']}")
        return res.get("result", {}).get("value")

    def screenshot(self, path, fmt="png"):
        res = self.send("Page.captureScreenshot", {"format": fmt, "fromSurface": True})
        data = base64.b64decode(res["data"])
        with open(path, "wb") as f:
            f.write(data)
        return len(data)

    def enable_page(self):
        self.send("Page.enable")
        self.send("Runtime.enable")
        self._page_enabled = True

    def close(self):
        self.ws.close()
