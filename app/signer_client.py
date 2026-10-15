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
import sys
import threading
from pathlib import Path

SIGNER_DIR = Path(__file__).resolve().parent.parent / "signer"
SIGNER_SCRIPT = SIGNER_DIR / "signer.js"


def _bundled_base() -> Path | None:
    """PyInstaller extraction dir, when running from a frozen bundle."""
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else None


def _resolve_node(node_bin: str | None = None) -> str:
    """Locate the Node binary: explicit arg > env > bundled > PATH."""
    if node_bin:
        return node_bin
    env_bin = os.environ.get("SIGNER_NODE_BIN")
    if env_bin:
        return env_bin
    base = _bundled_base()
    if base:
        for name in ("node.exe", "node"):
            candidate = base / "node" / name
            if candidate.is_file():
                return str(candidate)
    return "node"


def _resolve_signer_dir() -> Path:
    """Locate the signer directory: bundled first, then repo layout."""
    base = _bundled_base()
    if base:
        bundled = base / "signer"
        if (bundled / "signer.js").is_file():
            return bundled
    return SIGNER_DIR


class SignerError(RuntimeError):
    pass


class DouyinSigner:
    """Manages a persistent ``node signer.js`` subprocess."""

    def __init__(self, node_bin: str | None = None, timeout: float = 30.0) -> None:
        self._node = _resolve_node(node_bin)
        self._timeout = timeout
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._counter = 0

    @property
    def available(self) -> bool:
        signer_dir = _resolve_signer_dir()
        if not (signer_dir / "signer.js").is_file():
            return False
        node = Path(self._node)
        if node.is_absolute() or os.sep in self._node:
            return node.is_file()
        return shutil.which(self._node) is not None

    def _start(self) -> None:
        signer_dir = _resolve_signer_dir()
        self._proc = subprocess.Popen(
            [self._node, str(signer_dir / "signer.js")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            cwd=str(signer_dir),
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
