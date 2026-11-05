"""A local CONNECT relay that authenticates to an upstream proxy.

Chromium refuses `net::ERR_PROXY_AUTH_UNSUPPORTED` for proxies needing
Proxy-Authorization (Playwright/patchright pass the credentials poorly).
This relay listens on 127.0.0.1 with NO auth, and injects a Basic
Proxy-Authorization header when it opens the upstream connection. The
browser sees a plain local proxy; the residential upstream sees its
rotating session identity.

    relay = Relay("geo.iproyal.com", 12321, "user", "pass")
    relay.start()          # relay.port is set
    ... launch chromium with proxy={"server": f"http://127.0.0.1:{relay.port}"}
    relay.stop()
"""
import base64
import selectors
import socket
import threading


class Relay:
    def __init__(self, host: str, port: int, user: str, password: str):
        self.upstream = (host, port)
        self.auth = base64.b64encode(f"{user}:{password}".encode()).decode()
        self.port = None
        self._sock = None
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        s.listen(64)
        self._sock = s
        self.port = s.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass

    # -- internals ---------------------------------------------------------

    def _serve(self):
        self._sock.settimeout(0.5)
        while not self._stop.is_set():
            try:
                client, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle, args=(client,),
                             daemon=True).start()

    def _handle(self, client: socket.socket):
        sel = selectors.DefaultSelector()
        try:
            client.settimeout(15)
            head = b""
            while b"\r\n\r\n" not in head:
                chunk = client.recv(65536)
                if not chunk:
                    return
                head += chunk
            first = head.split(b"\r\n", 1)[0]
            method = first.split(b" ")[0]
            upstream = socket.create_connection(self.upstream, timeout=20)
            if method == b"CONNECT":
                upstream.sendall(
                    first + b"\r\nProxy-Authorization: Basic "
                    + self.auth.encode() + b"\r\n\r\n")
                # read upstream's 2xx (or error) before relaying
                resp = b""
                while b"\r\n\r\n" not in resp:
                    chunk = upstream.recv(65536)
                    if not chunk:
                        client.close()
                        return
                    resp += chunk
                client.sendall(resp)
                if b" 200 " not in resp.split(b"\r\n", 1)[0]:
                    return
            else:               # plain HTTP: forward the request, auth in it
                upstream.sendall(head.replace(
                    b"\r\n\r\n",
                    b"\r\nProxy-Authorization: Basic "
                    + self.auth.encode() + b"\r\n\r\n", 1))
            for sock in (client, upstream):
                sock.setblocking(False)
                sel.register(sock, selectors.EVENT_READ)
            live = {client, upstream}
            while live:
                for key, _ in sel.select(timeout=30):
                    try:
                        data = key.fileobj.recv(65536)
                    except (BlockingIOError, socket.timeout):
                        continue
                    except OSError:
                        data = b""
                    if not data:
                        live.discard(key.fileobj)
                        try:
                            sel.unregister(key.fileobj)
                        except (KeyError, ValueError):
                            pass
                        continue
                    other = upstream if key.fileobj is client else client
                    try:
                        other.sendall(data)
                    except OSError:
                        live.discard(key.fileobj)
        except OSError:
            pass
        finally:
            for sock in (client, locals().get("upstream")):
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass
