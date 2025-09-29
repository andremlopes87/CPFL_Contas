"""Configuration helpers for CPFL pipeline."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from dotenv import load_dotenv

LOGGER = logging.getLogger(__name__)


@dataclass
class ClientConfig:
    """Configuration for a single client installation."""

    cliente: str
    numero_instalacao: str
    numero_cliente: Optional[str]
    email_cliente: Optional[str]
    login: Optional[str]
    senha: Optional[str]
    cpf4: Optional[str]
    pasta_entrada: Optional[str]

    @property
    def slug(self) -> str:
        return self.cliente.lower().replace(" ", "_")


@dataclass
class AppConfig:
    """Top level configuration for the pipeline."""

    inbox_dir: Path
    archive_dir: Path
    output_dir: Path
    config_path: Path

    @property
    def json_output_dir(self) -> Path:
        return self.output_dir / "json"

    @property
    def master_table_path(self) -> Path:
        return self.output_dir / "cpfl_faturas_master.csv"

    @property
    def master_excel_path(self) -> Path:
        return self.output_dir / "cpfl_faturas_master.xlsx"


DEFAULT_CONFIG_LOCATIONS: Iterable[Path] = (
    Path("config/clients_config.json"),
    Path("config/clients_config.sample.json"),
)


def load_environment() -> None:
    """Load environment variables from .env if present."""

    env_path = Path(".env")
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
        LOGGER.debug("Environment variables loaded from %s", env_path)
    else:
        load_dotenv()
        LOGGER.debug("Environment variables loaded from default search path")


def resolve_app_config(config_path: Optional[str] = None) -> AppConfig:
    """Build application configuration from environment and defaults."""

    load_environment()

    inbox = Path(os.getenv("CPFL_INBOX_DIR", "data/incoming"))
    archive = Path(os.getenv("CPFL_ARCHIVE_DIR", "data/archive"))
    output = Path(os.getenv("CPFL_OUTPUT_DIR", "data/output"))

    if config_path:
        config_file = Path(config_path)
    else:
        for candidate in DEFAULT_CONFIG_LOCATIONS:
            if candidate.exists():
                config_file = candidate
                break
        else:
            raise FileNotFoundError(
                "Nenhum arquivo de configuração encontrado. Crie config/clients_config.json a partir do sample."
            )

    archive.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    (output / "json").mkdir(parents=True, exist_ok=True)

    return AppConfig(
        inbox_dir=inbox,
        archive_dir=archive,
        output_dir=output,
        config_path=config_file,
    )


def load_clients(config_path: Path) -> List[ClientConfig]:
    """Load client definitions from JSON file."""

    with config_path.open("r", encoding="utf-8") as fp:
        payload: Dict[str, List[Dict[str, Optional[str]]]] = json.load(fp)

    clients: List[ClientConfig] = []
    for entry in payload.get("clientes", []):
        clients.append(
            ClientConfig(
                cliente=entry.get("cliente", ""),
                numero_instalacao=str(entry.get("numero_instalacao", "")),
                numero_cliente=(entry.get("numero_cliente") or None),
                email_cliente=(entry.get("email_cliente") or None),
                login=(entry.get("login") or None),
                senha=(entry.get("senha") or None),
                cpf4=(entry.get("cpf4") or None),
                pasta_entrada=(entry.get("pasta_entrada") or None),
            )
        )

    if not clients:
        raise ValueError("Arquivo de configuração não possui clientes cadastrados.")

    return clients


__all__ = ["ClientConfig", "AppConfig", "resolve_app_config", "load_clients", "load_environment"]
