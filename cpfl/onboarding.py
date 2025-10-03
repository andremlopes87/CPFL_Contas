"""Interactive onboarding flow to prepare the collector configuration."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from .config import APP_DIR_NAME, DEFAULT_CONFIG_PATH
from .utils import resource_path


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

    target.write_text(json.dumps(template_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Configuração salva em {target}")
    print("Preencha os tokens/payloads da UC conforme as instruções do README antes de executar a coleta real.")


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


__all__ = ["ensure_config", "run_onboarding", "APP_DIR_NAME"]
