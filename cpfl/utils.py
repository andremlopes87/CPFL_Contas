"""Shared utilities for the CPFL API collector."""
from __future__ import annotations

import json
import logging
import os
import queue
import re
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Optional

try:
    import requests
    from requests.adapters import HTTPAdapter
except ImportError:  # pragma: no cover - fallback for environments sem requests
    requests = None  # type: ignore[assignment]
    HTTPAdapter = None  # type: ignore[assignment]

try:  # pragma: no cover - fallback para ambientes sem urllib3
    from urllib3.util.retry import Retry  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - fallback para ambientes sem urllib3
    Retry = None  # type: ignore[assignment]

LOGGER = logging.getLogger("cpfl")


DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://servicosonline.cpfl.com.br",
    "Referer": "https://servicosonline.cpfl.com.br/agencia-webapp/",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/121.0 Safari/537.36"
    ),
}


@dataclass
class BookmarkletResult:
    """Result returned by the bookmarklet server."""

    access_token: Optional[str]
    refresh_token: Optional[str]
    expires_at: Optional[str]
    key: Optional[str]


class BookmarkletRequestHandler(BaseHTTPRequestHandler):
    """HTTP handler that collects bookmarklet payloads."""

    server_version = "CPFLCollector/1.0"

    def do_POST(self) -> None:  # noqa: N802 - API required name
        if self.path.rstrip("/") != "/push":
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(length).decode("utf-8")
        try:
            data = json.loads(payload or "{}")
        except json.JSONDecodeError:
            LOGGER.error("Payload inválido recebido pelo bookmarklet")
            self.send_response(400)
            self.end_headers()
            return

        LOGGER.info("Tokens recebidos via bookmarklet")
        result = BookmarkletResult(
            access_token=data.get("access_token") or data.get("token"),
            refresh_token=data.get("refresh_token"),
            expires_at=data.get("expires_at") or data.get("exp"),
            key=data.get("key"),
        )
        self.server.result_queue.put(result)  # type: ignore[attr-defined]
        self.send_response(204)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003 - required signature
        LOGGER.debug("Bookmarklet server: " + format, *args)


class BookmarkletServer:
    """Simple local HTTP server used to capture bookmarklet tokens."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.host = host
        self.port = port
        self._queue: "queue.Queue[BookmarkletResult]" = queue.Queue()
        self._server = HTTPServer((self.host, self.port), BookmarkletRequestHandler)
        self._server.result_queue = self._queue  # type: ignore[attr-defined]
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        LOGGER.info("Iniciando servidor local para receber tokens do bookmarklet em %s:%s", self.host, self.port)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._thread:
            return
        LOGGER.info("Encerrando servidor local do bookmarklet")
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)
        self._thread = None

    def wait_for_tokens(self, timeout: int = 180) -> Optional[BookmarkletResult]:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    @property
    def bookmarklet_snippet(self) -> str:
        return (
            "javascript:(function(){try{const key=(location.hash.split('key=')[1]||'').split('&')[0];"
            "const payload={key:key||null,access_token:localStorage.getItem('access_token'),"
            "refresh_token:localStorage.getItem('refresh_token'),"
            "expires_at:localStorage.getItem('expires_in')||localStorage.getItem('token_expiration')||null};"
            f"fetch('http://{self.host}:{self.port}/push',{{method:'POST',headers:{{'Content-Type':'application/json'}},"
            "body:JSON.stringify(payload)}}).then(()=>alert('Tokens enviados para o coletor CPFL.'))"
            ".catch(err=>alert('Falha ao enviar tokens: '+err));}catch(err){alert('Erro: '+err);}})();"
        )

    @contextmanager
    def running(self) -> Iterator["BookmarkletServer"]:
        try:
            self.start()
            yield self
        finally:
            self.stop()


def create_retry_session(
    retries: int = 3,
    backoff_factor: float = 0.5,
    status_forcelist: Iterable[int] | None = None,
):
    if requests is None:
        raise RuntimeError(
            "Biblioteca 'requests' não está instalada. Instale-a para executar a coleta real."
        )
    session = requests.Session()
    if Retry and HTTPAdapter:
        retry = Retry(
            total=retries,
            read=retries,
            connect=retries,
            backoff_factor=backoff_factor,
            status_forcelist=status_forcelist or (500, 502, 503, 504, 429),
            allowed_methods=("GET", "POST", "PUT", "DELETE", "OPTIONS"),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
    session.headers.update(DEFAULT_HEADERS.copy())
    return session


def setup_logging(level: str = "INFO") -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        LOGGER.debug("Não foi possível interpretar data ISO %s", value)
        return None
    return dt


def safe_write_json(target: Path, data: Any) -> None:
    ensure_directory(target.parent)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower())
    normalized = re.sub(r"-+", "-", normalized)
    return normalized.strip("-") or "uc"


def environ_bool(var_name: str, default: bool = False) -> bool:
    raw = os.getenv(var_name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def resource_path(*parts: str) -> Path:
    """Return a filesystem path for bundled resources.

    Works for both normal execution and PyInstaller frozen binaries.
    """

    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return base.joinpath(*parts)


def mask_secret(value: Optional[str]) -> str:
    if not value:
        return "<vazio>"
    clean = value.strip()
    if len(clean) <= 12:
        return clean[:3] + "..." + clean[-3:]
    return f"{clean[:6]}...{clean[-6:]}"


__all__ = [
    "BookmarkletServer",
    "BookmarkletResult",
    "DEFAULT_HEADERS",
    "create_retry_session",
    "ensure_directory",
    "environ_bool",
    "isoformat",
    "parse_datetime",
    "resource_path",
    "mask_secret",
    "safe_write_json",
    "setup_logging",
    "slugify",
    "utcnow",
]
