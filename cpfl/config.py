"""Configuration helpers for the CPFL API collector."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .utils import isoformat, parse_datetime, slugify, utcnow


DEFAULT_CONFIG_PATH = Path("config.json")


@dataclass
class GlobalSettings:
    base_url: str = "https://servicosonline.cpfl.com.br/agencia-webapi/api"
    client_id: str = "agencia-virtual-cpfl-web"
    output_dir: Path = Path("out")
    download_pdfs: bool = False
    request_timeout: int = 20
    max_retries: int = 3
    backoff_factor: float = 0.6
    bookmarklet_port: int = 8765
    period_start: Optional[str] = None
    period_end: Optional[str] = None

    def resolve_paths(self, base_path: Path) -> None:
        if not self.output_dir.is_absolute():
            self.output_dir = (base_path / self.output_dir).resolve()


@dataclass
class AuthTokens:
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_at: Optional[datetime] = None


@dataclass
class UCConfig:
    uid: str
    descricao: str
    payload: Dict[str, Any]
    key: Optional[str]
    tokens: AuthTokens = field(default_factory=AuthTokens)
    extra_headers: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def slug(self) -> str:
        return slugify(self.descricao or self.uid)


class ConfigStore:
    """Wrapper that loads and persists the collector configuration."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = (path or DEFAULT_CONFIG_PATH).expanduser().resolve()
        if not self.path.exists():
            raise FileNotFoundError(
                f"Arquivo de configuração {self.path} não encontrado. Crie a partir de config.example.json."
            )

        with self.path.open("r", encoding="utf-8") as stream:
            self._raw_data: Dict[str, Any] = json.load(stream)

        base_path = self.path.parent
        self.settings = self._load_global_settings(base_path)
        self.uc_configs: List[UCConfig] = self._load_uc_configs(base_path)
        self._index = {uc.uid: idx for idx, uc in enumerate(self.uc_configs)}

    def _load_global_settings(self, base_path: Path) -> GlobalSettings:
        payload = self._raw_data.get("global", {})
        settings = GlobalSettings(
            base_url=payload.get("base_url", GlobalSettings.base_url),
            client_id=payload.get("client_id", GlobalSettings.client_id),
            output_dir=Path(payload.get("output_dir", "out")),
            download_pdfs=bool(payload.get("download_pdfs", False)),
            request_timeout=int(payload.get("request_timeout", 20)),
            max_retries=int(payload.get("max_retries", 3)),
            backoff_factor=float(payload.get("backoff_factor", 0.6)),
            bookmarklet_port=int(payload.get("bookmarklet_port", 8765)),
            period_start=payload.get("period_start"),
            period_end=payload.get("period_end"),
        )
        settings.resolve_paths(base_path)
        return settings

    def _load_uc_configs(self, base_path: Path) -> List[UCConfig]:
        entries = self._raw_data.get("unidades_consumidoras", [])
        configs: List[UCConfig] = []
        for index, entry in enumerate(entries):
            uid = entry.get("id") or entry.get("uid") or f"uc-{index+1}"
            descricao = entry.get("descricao") or entry.get("apelido") or uid
            payload = self._resolve_payload(entry, base_path)
            tokens = AuthTokens(
                access_token=entry.get("access_token"),
                refresh_token=entry.get("refresh_token"),
                expires_at=parse_datetime(entry.get("expires_at")),
            )
            uc = UCConfig(
                uid=str(uid),
                descricao=str(descricao),
                payload=payload,
                key=entry.get("key"),
                tokens=tokens,
                extra_headers=entry.get("headers") or {},
                metadata=self._extract_metadata(entry),
            )
            configs.append(uc)
        if not configs:
            raise ValueError("Nenhuma unidade consumidora configurada em config.json")
        return configs

    def _resolve_payload(self, entry: Dict[str, Any], base_path: Path) -> Dict[str, Any]:
        if "payload" in entry:
            payload = entry.get("payload")
            if isinstance(payload, dict):
                return payload
        if "body" in entry and isinstance(entry["body"], dict):
            return entry["body"]

        payload_file = entry.get("payload_file") or entry.get("inst_cache_file")
        if payload_file:
            payload_path = (base_path / payload_file).expanduser()
            if not payload_path.exists():
                raise FileNotFoundError(f"Arquivo de payload {payload_path} não encontrado")
            with payload_path.open("r", encoding="utf-8") as stream:
                payload_data = json.load(stream)
            payload_key = entry.get("payload_key") or entry.get("inst_cache_key")
            if payload_key:
                if payload_key not in payload_data:
                    raise KeyError(
                        f"Chave {payload_key} não encontrada em {payload_path}"
                    )
                candidate = payload_data[payload_key]
                if not isinstance(candidate, dict):
                    raise ValueError(f"Entrada {payload_key} de {payload_path} não é um objeto JSON")
                return candidate
            if isinstance(payload_data, dict):
                return payload_data
        raise ValueError(
            "Configuração da UC não contém payload válido (use 'payload' ou 'payload_file')."
        )

    def _extract_metadata(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        ignored = {
            "id",
            "uid",
            "descricao",
            "apelido",
            "payload",
            "body",
            "payload_file",
            "payload_key",
            "inst_cache_file",
            "inst_cache_key",
            "access_token",
            "refresh_token",
            "expires_at",
            "key",
            "headers",
        }
        return {k: v for k, v in entry.items() if k not in ignored}

    def save(self) -> None:
        with self.path.open("w", encoding="utf-8") as stream:
            json.dump(self._raw_data, stream, ensure_ascii=False, indent=2)

    # Public API -----------------------------------------------------------------
    def iter_uc(self) -> Iterable[UCConfig]:
        return list(self.uc_configs)

    def get_uc(self, uid: str) -> UCConfig:
        return self.uc_configs[self._index[uid]]

    def update_tokens(
        self,
        uid: str,
        *,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        key: Optional[str] = None,
    ) -> UCConfig:
        uc = self.get_uc(uid)
        raw_entry = self._raw_data["unidades_consumidoras"][self._index[uid]]

        if access_token is not None:
            uc.tokens.access_token = access_token
            raw_entry["access_token"] = access_token
        if refresh_token is not None:
            uc.tokens.refresh_token = refresh_token
            raw_entry["refresh_token"] = refresh_token
        if expires_at is not None:
            uc.tokens.expires_at = expires_at
            raw_entry["expires_at"] = isoformat(expires_at) if expires_at else None
        if key is not None:
            uc.key = key
            raw_entry["key"] = key

        raw_entry["updated_at"] = isoformat(utcnow())
        self.save()
        return uc

    def set_key(self, uid: str, key: str) -> None:
        self.update_tokens(uid, key=key)


__all__ = ["ConfigStore", "GlobalSettings", "UCConfig", "AuthTokens", "DEFAULT_CONFIG_PATH"]
