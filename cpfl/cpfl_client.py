"""HTTP client responsible for interacting with the CPFL API."""
from __future__ import annotations

import logging
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, TYPE_CHECKING
from urllib.parse import urljoin

if TYPE_CHECKING:  # pragma: no cover
    import requests  # type: ignore[import]
else:  # pragma: no cover - ambiente de testes sem requests
    try:
        import requests  # type: ignore[import]
    except ImportError:  # pragma: no cover - usado apenas quando requests indisponível
        requests = None  # type: ignore[assignment]

from .config import GlobalSettings, UCConfig
from .utils import (
    BookmarkletServer,
    BookmarkletResult,
    create_retry_session,
    mask_secret,
    utcnow,
)

LOGGER = logging.getLogger("cpfl.client")


class CPFLAPIError(RuntimeError):
    """Raised when the CPFL API returns an error."""

    def __init__(self, message: str, *, status_code: Optional[int] = None, payload: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class AuthorizationError(CPFLAPIError):
    """Raised when the API denies authorization."""


@dataclass
class TokenBundle:
    access_token: str
    refresh_token: Optional[str]
    expires_at: Optional[datetime]


class CPFLClient:
    def __init__(self, settings: GlobalSettings, uc: UCConfig) -> None:
        self.settings = settings
        self.uc = uc
        self.session = create_retry_session(retries=settings.max_retries, backoff_factor=settings.backoff_factor)
        for key, value in uc.extra_headers.items():
            self.session.headers[key] = value
        if uc.tokens.access_token:
            self.session.headers["Authorization"] = f"Bearer {uc.tokens.access_token}"

    # ------------------------------------------------------------------
    def _build_url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return urljoin(self.settings.base_url.rstrip("/") + "/", path.lstrip("/"))

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_payload: Any | None = None,
        params: Dict[str, Any] | None = None,
        data: Any | None = None,
        timeout: Optional[int] = None,
        allow_unauthorized: bool = False,
        stream: bool = False,
    ):
        if requests is None:
            raise RuntimeError("Biblioteca 'requests' não instalada")
        url = self._build_url(path)
        try:
            response = self.session.request(
                method,
                url,
                json=json_payload,
                params=params,
                data=data,
                timeout=timeout or self.settings.request_timeout,
                stream=stream,
            )
        except requests.RequestException as exc:
            raise CPFLAPIError(f"Erro de rede ao chamar {url}: {exc}") from exc

        if response.status_code in {401, 403} and not allow_unauthorized:
            raise AuthorizationError(
                f"Token não autorizado para {path}",
                status_code=response.status_code,
                payload=_safe_json(response),
            )
        if response.status_code >= 400:
            raise CPFLAPIError(
                f"Erro {response.status_code} ao chamar {path}",
                status_code=response.status_code,
                payload=_safe_json(response),
            )
        return response

    # ------------------------------------------------------------------
    def check_roles(self) -> bool:
        LOGGER.info("Validando token atual em /user/roles")
        try:
            self._request("GET", "/user/roles", params={"clientId": self.settings.client_id})
            return True
        except AuthorizationError:
            return False

    def refresh_access_token(self) -> Optional[TokenBundle]:
        if not self.uc.tokens.refresh_token:
            LOGGER.warning("UC %s não possui refresh_token cadastrado", self.uc.uid)
            return None

        url = self._build_url("/token")
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self.uc.tokens.refresh_token,
            "client_id": self.settings.client_id,
        }
        headers = {key: value for key, value in self.session.headers.items() if key.lower() != "authorization"}
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        LOGGER.info("Tentando renovar access_token via refresh_token")
        try:
            response = self.session.post(
                url,
                data=payload,
                headers=headers,
                timeout=self.settings.request_timeout,
            )
        except requests.RequestException as exc:
            raise CPFLAPIError(f"Falha de rede ao renovar token: {exc}") from exc

        if response.status_code >= 400:
            LOGGER.warning("Refresh token falhou com status %s", response.status_code)
            return None

        data = _safe_json(response) or {}
        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token") or self.uc.tokens.refresh_token
        expires_in = data.get("expires_in")
        expires_at: Optional[datetime] = None
        if expires_in:
            try:
                expires_at = utcnow() + timedelta(seconds=int(expires_in))
            except (TypeError, ValueError):
                expires_at = None
        if not access_token:
            LOGGER.error("Resposta de refresh não contém access_token: %s", data)
            return None

        LOGGER.info("Refresh token aceito, novo access_token obtido")
        return TokenBundle(access_token=access_token, refresh_token=refresh_token, expires_at=expires_at)

    def update_tokens(self, token_bundle: TokenBundle) -> None:
        self.uc.tokens.access_token = token_bundle.access_token
        self.uc.tokens.refresh_token = token_bundle.refresh_token
        self.uc.tokens.expires_at = token_bundle.expires_at
        self.session.headers["Authorization"] = f"Bearer {token_bundle.access_token}"
        LOGGER.info(
            "Sessão atualizada (access=%s | refresh=%s)",
            mask_secret(token_bundle.access_token),
            mask_secret(token_bundle.refresh_token),
        )

    def ensure_authenticated(self) -> tuple[bool, Optional[TokenBundle]]:
        if self.uc.tokens.access_token and self.check_roles():
            return True, None
        LOGGER.info("Token inválido para UC %s", self.uc.uid)
        bundle = self.refresh_access_token()
        if bundle:
            self.update_tokens(bundle)
            if self.check_roles():
                return True, bundle
        return False, None

    def handshake(self) -> Dict[str, Any]:
        if not self.uc.key:
            raise AuthorizationError("UC não possui key para integração. Capture via bookmarklet.")
        params = {"key": self.uc.key, "url": "/historico-contas"}
        LOGGER.info("Executando handshake /user/validar-integracao")
        response = self._request("GET", "/user/validar-integracao", params=params)
        return _safe_json(response) or {}

    def fetch_paid_history(self) -> Dict[str, Any]:
        LOGGER.info("Consultando /historico-contas/contas-quitadas")
        response = self._request(
            "POST",
            "/historico-contas/contas-quitadas",
            params={"clientId": self.settings.client_id},
            json_payload=self.uc.payload,
        )
        return _safe_json(response) or {}

    def fetch_status_history(self) -> Dict[str, Any]:
        LOGGER.info("Consultando /historico-contas/validar-situacao")
        response = self._request(
            "POST",
            "/historico-contas/validar-situacao",
            params={"clientId": self.settings.client_id},
            json_payload=self.uc.payload,
        )
        return _safe_json(response) or {}

    def download_pdf(self, url: str, target_path: Path) -> None:
        LOGGER.info("Baixando PDF da fatura em %s", url)
        response = self._request("GET", url, stream=True)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with target_path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 64):
                if chunk:
                    handle.write(chunk)
        LOGGER.debug("PDF salvo em %s", target_path)

    # Bookmarklet helper ---------------------------------------------------------
    def capture_tokens_via_bookmarklet(self, timeout: int = 180) -> Optional[TokenBundle]:
        server = BookmarkletServer(port=self.settings.bookmarklet_port)
        with server.running():
            LOGGER.warning("Executar bookmarklet no navegador logado para enviar tokens.")
            LOGGER.warning("Bookmarklet: %s", server.bookmarklet_snippet)
            LOGGER.warning(
                "Abra a página 'Débitos e 2ª via / Histórico' e clique no favorito do bookmarklet."
            )
            try:
                webbrowser.open(
                    "https://servicosonline.cpfl.com.br/agencia-webapp/#/historico-contas",
                    new=2,
                    autoraise=True,
                )
            except Exception as exc:  # pragma: no cover - depende do SO
                LOGGER.debug("Não foi possível abrir o navegador automaticamente: %s", exc)
            result = server.wait_for_tokens(timeout=timeout)
        if not result:
            LOGGER.error("Nenhum token recebido do bookmarklet dentro do tempo limite")
            return None
        bundle = self._bundle_from_bookmarklet(result)
        if bundle:
            LOGGER.info(
                "Tokens recebidos (access=%s | refresh=%s)",
                mask_secret(bundle.access_token),
                mask_secret(bundle.refresh_token),
            )
        return bundle

    def _bundle_from_bookmarklet(self, result: BookmarkletResult) -> Optional[TokenBundle]:
        if not result.access_token:
            LOGGER.error("Bookmarklet não retornou access_token")
            return None
        expires_at = None
        if result.expires_at:
            try:
                expires_seconds = int(result.expires_at)
                if expires_seconds > 1e6:
                    expires_at = datetime.fromtimestamp(expires_seconds, tz=utcnow().tzinfo)
                else:
                    expires_at = utcnow() + timedelta(seconds=expires_seconds)
            except (TypeError, ValueError):
                expires_at = None
        if result.key:
            self.uc.key = result.key
        LOGGER.info("Tokens obtidos via bookmarklet")
        return TokenBundle(
            access_token=result.access_token,
            refresh_token=result.refresh_token,
            expires_at=expires_at,
        )


def _safe_json(response: Any) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


__all__ = ["CPFLClient", "CPFLAPIError", "AuthorizationError", "TokenBundle"]
