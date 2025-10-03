"""Interactive onboarding flow to prepare the collector configuration."""
from __future__ import annotations

import json
import re
from getpass import getpass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .config import APP_DIR_NAME, DEFAULT_CONFIG_PATH, ConfigStore, UCConfig
from .utils import mask_secret, resource_path


def ensure_config(config_path: Path | None = None) -> Path:
    target = (config_path or DEFAULT_CONFIG_PATH).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        run_onboarding(target)
    return target


def run_onboarding(target: Path) -> None:
    print("=== Primeiro uso do CPFL Fetcher ===")
    template_data = _load_template()
    print("Arquivo de configuração base carregado.")

    ucs: List[Dict[str, Any]] = template_data.get("unidades_consumidoras", [])
    if not ucs:
        raise RuntimeError("Template de configuração não contém unidades consumidoras.")

    print("Informe uma descrição amigável para cada UC (pressione Enter para manter).")
    for index, entry in enumerate(ucs, start=1):
        current = entry.get("descricao") or entry.get("id") or entry.get("uid") or f"UC {index}"
        print(f"[{index}] {current}")
        new_value = input("Descrição exibida: ").strip()
        if new_value:
            entry["descricao"] = new_value

    global_section: Dict[str, Any] = template_data.setdefault("global", {})
    current_pdf = bool(global_section.get("download_pdfs", False))
    answer = input(
        f"Baixar PDFs automaticamente? (s/n) [{'s' if current_pdf else 'n'}]: "
    ).strip().lower()
    if answer in {"s", "sim", "y", "yes"}:
        global_section["download_pdfs"] = True
    elif answer in {"n", "nao", "não", "no"}:
        global_section["download_pdfs"] = False

    print("Informe um intervalo opcional de meses no formato AAAA-MM. Deixe em branco para usar o padrão.")
    global_section["period_start"] = _prompt_month("Período inicial (AAAA-MM): ", global_section.get("period_start"))
    global_section["period_end"] = _prompt_month("Período final (AAAA-MM): ", global_section.get("period_end"))

    _prompt_uc_sensitive_fields(ucs)

    target.write_text(json.dumps(template_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Configuração salva em {target}")
    print("Você pode ajustar tokens ou payloads depois executando novamente o aplicativo.")


def _prompt_month(prompt: str, default: str | None) -> str | None:
    pattern = re.compile(r"^\d{4}-\d{2}$")
    while True:
        raw = input(prompt).strip()
        if not raw:
            return default
        if pattern.match(raw):
            return raw
        print("Formato inválido. Utilize AAAA-MM.")


def _load_template() -> Dict[str, Any]:
    template_path = resource_path("config.example.json")
    if not template_path.exists():
        raise FileNotFoundError(
            "config.example.json não encontrado. Verifique se o pacote foi instalado corretamente."
        )
    with template_path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def review_sensitive_fields(store: ConfigStore) -> None:
    """Solicita valores ausentes para tokens, key e payload das UCs."""

    pending = [uc for uc in store.iter_uc() if _needs_review(uc)]
    if not pending:
        return

    print("Revendo credenciais das unidades consumidoras. Pressione Enter para manter valores atuais.")
    for uc in pending:
        _prompt_for_uc(store, uc, show_header=True)


def _prompt_uc_sensitive_fields(entries: Iterable[Dict[str, Any]]) -> None:
    for entry in entries:
        payload = entry.get("payload")
        descricao = entry.get("descricao") or entry.get("id") or entry.get("uid") or "UC"
        print(f"-- Dados da UC {descricao} --")
        entry["key"] = _prompt_plain(
            "Key da URL (#/integracao-agd?key=...)",
            entry.get("key"),
            required=False,
        )
        entry["access_token"] = _prompt_secret(
            "Access token (JWT)",
            entry.get("access_token"),
            required=False,
        )
        entry["refresh_token"] = _prompt_secret(
            "Refresh token (JWT)",
            entry.get("refresh_token"),
            required=False,
        )
        entry["expires_at"] = _prompt_plain(
            "Expiração do access token (ISO 8601, opcional)",
            entry.get("expires_at"),
            required=False,
        )

        if isinstance(payload, dict) and payload:
            print("Informe os campos do payload criptografado (copie do inst_cache.json).")
            for field_name, current in payload.items():
                payload[field_name] = _prompt_plain(
                    f"{field_name}",
                    current,
                    required=_looks_placeholder(current),
                )
        print("")


def _prompt_for_uc(store: ConfigStore, uc: UCConfig, *, show_header: bool) -> None:
    needs_key = _looks_placeholder(uc.key)
    needs_access = _looks_placeholder(uc.tokens.access_token)
    needs_refresh = _looks_placeholder(uc.tokens.refresh_token)
    payload_updates: Dict[str, Any] = {}
    for field_name, value in uc.payload.items():
        if _looks_placeholder(value):
            payload_updates[field_name] = value

    if not any([needs_key, needs_access, needs_refresh, payload_updates]):
        return

    if show_header:
        print("")
        print(f"-- Atualizando dados da UC {uc.descricao} (ID {uc.uid}) --")

    if needs_key:
        new_key = _prompt_plain("Key da URL", uc.key, required=False)
        if new_key and new_key != uc.key:
            store.update_tokens(uc.uid, key=new_key)

    if needs_access:
        new_access = _prompt_secret(
            "Access token (JWT)",
            uc.tokens.access_token,
            required=False,
        )
        if new_access and new_access != uc.tokens.access_token:
            store.update_tokens(uc.uid, access_token=new_access)

    if needs_refresh:
        new_refresh = _prompt_secret(
            "Refresh token (JWT)",
            uc.tokens.refresh_token,
            required=False,
        )
        if new_refresh and new_refresh != uc.tokens.refresh_token:
            store.update_tokens(uc.uid, refresh_token=new_refresh)

    if payload_updates:
        print("Campos obrigatórios do payload:")
        updated_payload = dict(uc.payload)
        for field_name in sorted(payload_updates):
            updated_payload[field_name] = _prompt_plain(
                f"{field_name}",
                uc.payload.get(field_name),
                required=True,
            )
        store.update_payload(uc.uid, updated_payload)


def _needs_review(uc: UCConfig) -> bool:
    if _looks_placeholder(uc.key):
        return True
    if _looks_placeholder(uc.tokens.access_token):
        return True
    if _looks_placeholder(uc.tokens.refresh_token):
        return True
    for value in uc.payload.values():
        if _looks_placeholder(value):
            return True
    return False


PLACEHOLDER_TOKENS = ["SUBSTITUA", "EXEMPLO", "DEMO", "CHAVE", "JWT"]
PLACEHOLDER_PAYLOAD = ["CRIPTO_", "SUBSTITUA", "EXEMPLO", "DEMO"]


def _looks_placeholder(value: Optional[str]) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    cleaned = value.strip()
    if not cleaned:
        return True
    upper = cleaned.upper()
    if upper.startswith("EYJ") and len(cleaned) > 20:
        return False  # JWT real
    for fragment in PLACEHOLDER_TOKENS:
        if fragment in upper:
            return True
    for fragment in PLACEHOLDER_PAYLOAD:
        if fragment in upper:
            return True
    return False


def _prompt_plain(prompt: str, current: Optional[str], *, required: bool) -> Optional[str]:
    keep_allowed = bool(current) and not required
    suffix = " (Enter para manter atual)" if keep_allowed else ""
    while True:
        value = input(f"{prompt}{suffix}: ").strip()
        if value:
            return value
        if current and not required:
            return current
        if not required:
            return None
        print("Este campo é obrigatório.")


def _prompt_secret(prompt: str, current: Optional[str], *, required: bool = False) -> Optional[str]:
    masked = mask_secret(current) if current else None
    text_prompt = f"{prompt}"
    if masked and not required:
        text_prompt += f" (Enter para manter {masked})"
    else:
        text_prompt += " (cole o valor e pressione Enter)"
    while True:
        try:
            value = getpass(f"{text_prompt}: ")
        except Exception:
            value = input(f"{text_prompt}: ")
        value = value.strip()
        if value:
            return value
        if current and not required:
            return current
        if not required:
            return None
        print("Este campo é obrigatório.")


__all__ = ["ensure_config", "run_onboarding", "review_sensitive_fields", "APP_DIR_NAME"]
