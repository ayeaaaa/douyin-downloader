"""Node-based Douyin web signer client.

Runs ``signer/signer.js`` (Node + jsdom) as a persistent subprocess and
requests signed URLs over an NDJSON protocol.  The signed URL carries
``a_bogus``, ``uifid``, ``timestamp`` and ``x-secsdk-web-signature`` and must
be fetched with a Firefox-like TLS fingerprint (``curl_cffi``
``impersonate="firefox"``) together with the same cookies.

The signer requires ``UIFID_TEMP`` (or ``UIFID``) in the cookies; export
browser cookies to satisfy this.
"""

from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import threading
from pathlib import Path

SIGNER_DIR = Path(__file__).resolve().parent.parent / "signer"
SIGNER_SCRIPT = SIGNER_DIR / "signer.js"


class SignerError(RuntimeError):
    pass


class DouyinSigner:
    """Manages a persistent ``node signer.js`` subprocess."""

    def __init__(self, node_bin: str | None = None, timeout: float = 30.0) -> None:
        self._node = node_bin or os.environ.get("SIGNER_NODE_BIN") or "node"
        self._timeout = timeout
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._counter = 0

    @property
    def available(self) -> bool:
        if not SIGNER_SCRIPT.is_file():
            return False
        return shutil.which(self._node) is not None

    def _start(self) -> None:
        self._proc = subprocess.Popen(
            [self._node, str(SIGNER_SCRIPT)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            cwd=str(SIGNER_DIR),
        )

    def _stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def sign(self, url_path: str, cookies: dict[str, str]) -> dict | None:
        """Return ``{"signedUrl", "headers", "cookies"}`` or ``None`` on failure."""
        if not self.available:
            return None
        with self._lock:
            for attempt in range(2):
                try:
                    return self._sign_once(url_path, cookies)
                except SignerError:
                    self._stop()
                    if attempt != 0:
                        return None
        return None

    def _sign_once(self, url_path: str, cookies: dict[str, str]) -> dict:
        if self._proc is None or self._proc.poll() is not None:
            self._start()
        assert self._proc and self._proc.stdin and self._proc.stdout
        self._counter += 1
        request = json.dumps(
            {"id": self._counter, "url": url_path, "cookies": cookies},
            ensure_ascii=False,
        )
        try:
            self._proc.stdin.write(request + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise SignerError(f"signer pipe error: {exc}") from exc

        ready, _, _ = select.select([self._proc.stdout], [], [], self._timeout)
        if not ready:
            raise SignerError("signer timeout")
        line = self._proc.stdout.readline()
        if not line:
            raise SignerError("signer exited")
        try:
            payload = json.loads(line)
        except ValueError as exc:
            raise SignerError("bad signer output") from exc
        if not payload.get("ok"):
            raise SignerError(payload.get("error") or "sign failed")
        return payload

    def close(self) -> None:
        with self._lock:
            self._stop()


_signer: DouyinSigner | None = None
_signer_lock = threading.Lock()


def get_signer() -> DouyinSigner:
    global _signer
    if _signer is None:
        with _signer_lock:
            if _signer is None:
                _signer = DouyinSigner()
    return _signer
