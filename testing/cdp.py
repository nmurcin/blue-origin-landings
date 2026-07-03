"""
Minimal Chrome DevTools Protocol (CDP) client — Python stdlib only.

No pip deps, no Node. Implements just enough of RFC 6455 (client-side
WebSocket) plus the CDP request/response + event loop to:
  - launch headless Chrome with a remote debugging port,
  - find the page target's ws debugger URL over HTTP,
  - send CDP commands and read their replies,
  - wait for CDP events (e.g. Page.loadEventFired),
  - evaluate JS in the page and read values back,
  - capture PNG screenshots.

Why hand-rolled: the one-shot `chrome --screenshot --virtual-time-budget`
mode is unreliable for a game with an infinite requestAnimationFrame loop
(the budget can expire while rAF is still pending and Chrome never reaches
quiescence, so no PNG is written — and each hung run leaks a process that
locks the user-data-dir). Driving a persistent headless Chrome over CDP is
deterministic: we poll the live game state and screenshot exactly when we want.

This is a client WebSocket, so masking is required (RFC 6455 §5.3) and we
never expect fragmented/continuation frames from Chrome in practice, but we
handle multi-frame reads defensively.
"""

import base64
import hashlib
import json
import os
import socket
import struct
import subprocess
import time
import urllib.request


class WSError(RuntimeError):
    pass


class WebSocket:
    """Tiny client-side WebSocket over a raw TCP socket (text frames only)."""

    def __init__(self, url, timeout=30.0):
        # url like ws://127.0.0.1:9222/devtools/page/<id>
        assert url.startswith("ws://"), url
        rest = url[len("ws://"):]
        hostport, _, path = rest.partition("/")
        path = "/" + path
        host, _, port = hostport.partition(":")
        port = int(port or 80)
        self._buf = b""
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
        resp = self._read_http_headers()
        if b"101" not in resp.split(b"\r\n", 1)[0]:
            raise WSError(f"WebSocket upgrade failed: {resp[:120]!r}")
        accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
        ).decode()
        if accept.encode() not in resp:
            raise WSError("Sec-WebSocket-Accept mismatch")

    def _read_http_headers(self):
        while b"\r\n\r\n" not in self._buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise WSError("connection closed during handshake")
            self._buf += chunk
        head, _, rest = self._buf.partition(b"\r\n\r\n")
        self._buf = rest
        return head

    def _recv_exact(self, n):
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise WSError("connection closed")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def send(self, text):
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

    def recv(self):
        """Return one complete text message (reassembling fragments)."""
        chunks = []
        while True:
            b0, b1 = self._recv_exact(2)
            fin = b0 & 0x80
            opcode = b0 & 0x0F
            masked = b1 & 0x80
            length = b1 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._recv_exact(8))[0]
            mask = self._recv_exact(4) if masked else b""
            data = self._recv_exact(length)
            if masked:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if opcode == 0x8:  # close
                raise WSError("server sent close frame")
            if opcode == 0x9:  # ping -> pong
                self._pong(data)
                continue
            if opcode == 0xA:  # pong
                continue
            chunks.append(data)
            if fin:
                break
        return b"".join(chunks).decode("utf-8", "replace")

    def _pong(self, data):
        header = bytearray([0x8A])
        mask = os.urandom(4)
        header.append(0x80 | len(data))
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self.sock.sendall(bytes(header) + masked)

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class Chrome:
    """Launch headless Chrome and speak CDP to its page target."""

    def __init__(self, chrome_path, user_data_dir, port=9222,
                 window=(1280, 900), extra_flags=None):
        self.chrome_path = chrome_path
        self.user_data_dir = user_data_dir
        self.port = port
        self.window = window
        self.extra_flags = extra_flags or []
        self.proc = None
        self.ws = None
        self._id = 0

    def launch(self, ready_timeout=25.0):
        w, h = self.window
        flags = [
            self.chrome_path,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.user_data_dir}",
            f"--window-size={w},{h}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
            "--disable-backgrounding-occluded-windows",
            "--mute-audio",
            "about:blank",
        ]
        flags[1:1] = self.extra_flags  # inject after chrome_path
        self.proc = subprocess.Popen(
            flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        ws_url = self._wait_for_page_target(ready_timeout)
        self.ws = WebSocket(ws_url)
        return self

    def _wait_for_page_target(self, timeout):
        deadline = time.time() + timeout
        last_err = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/json", timeout=2
                ) as r:
                    targets = json.loads(r.read().decode())
                for t in targets:
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                        return t["webSocketDebuggerUrl"]
            except Exception as e:  # noqa: BLE001 - retry until timeout
                last_err = e
            time.sleep(0.25)
        raise WSError(f"no page target after {timeout}s (last: {last_err})")

    def send(self, method, params=None, timeout=30.0):
        """Send a CDP command and return its result (blocks for the reply)."""
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method,
                                 "params": params or {}}))
        end = time.time() + timeout
        while time.time() < end:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise WSError(f"{method} error: {msg['error']}")
                return msg.get("result", {})
            # else: an event arrived before our reply — ignore it here
        raise WSError(f"timeout waiting for reply to {method}")

    def wait_event(self, method, timeout=30.0):
        end = time.time() + timeout
        while time.time() < end:
            msg = json.loads(self.ws.recv())
            if msg.get("method") == method:
                return msg.get("params", {})
        raise WSError(f"timeout waiting for event {method}")

    def eval(self, expr, timeout=30.0):
        """Runtime.evaluate returning the JSON-able value (returnByValue)."""
        res = self.send("Runtime.evaluate", {
            "expression": expr,
            "returnByValue": True,
            "awaitPromise": True,
        }, timeout=timeout)
        result = res.get("result", {})
        if result.get("subtype") == "error":
            raise WSError(f"JS error: {result.get('description')}")
        return result.get("value")

    def screenshot_png(self, path):
        res = self.send("Page.captureScreenshot", {"format": "png",
                                                   "captureBeyondViewport": False})
        data = base64.b64decode(res["data"])
        with open(path, "wb") as f:
            f.write(data)
        return len(data)

    def close(self):
        try:
            if self.ws:
                try:
                    self.send("Browser.close", timeout=3)
                except Exception:  # noqa: BLE001
                    pass
                self.ws.close()
        finally:
            if self.proc and self.proc.poll() is None:
                try:
                    self.proc.terminate()
                    self.proc.wait(timeout=5)
                except Exception:  # noqa: BLE001
                    try:
                        self.proc.kill()
                    except Exception:  # noqa: BLE001
                        pass
