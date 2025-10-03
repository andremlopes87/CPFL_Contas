"""Interactive console entry point used by the Windows executable."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .cli import run_collector
from .config import ConfigStore
from .onboarding import ensure_config, review_sensitive_fields
from .utils import setup_logging


def run(config_path: Path | None = None) -> int:
    print("=== CPFL Fetcher ===")
    resolved = ensure_config(config_path)
    print(f"Usando configuração em: {resolved}")

    try:
        store = ConfigStore(resolved)
    except Exception as exc:  # pragma: no cover - erros raros
        print(f"[ERRO] Não foi possível carregar a configuração: {exc}")
        return 2

    setup_logging("INFO")
    review_sensitive_fields(store)
    settings = store.settings
    _show_uc_summary(store)

    pdf_toggle = _prompt_yes_no(
        "Baixar PDFs nesta execução?",
        default=settings.download_pdfs,
    )
    start_override = _prompt_month(
        "Filtrar a partir de qual mês? (AAAA-MM, Enter para manter)",
        default=settings.period_start,
    )
    end_override = _prompt_month(
        "Filtrar até qual mês? (AAAA-MM, Enter para manter)",
        default=settings.period_end,
    )

    print("Iniciando a coleta. Fique atento às instruções exibidas abaixo.")
    exit_code = run_collector(
        resolved,
        download_pdfs=pdf_toggle if pdf_toggle is not None else None,
        period_start=start_override or settings.period_start,
        period_end=end_override or settings.period_end,
        allow_onboarding=True,
    )

    if exit_code == 0:
        print("Coleta finalizada. Consulte a pasta 'out' ao lado do config para CSV/PDF/JSON.")
    else:
        print("Coleta terminou com avisos. Revise os logs acima para detalhes.")
    return exit_code


def _show_uc_summary(store: ConfigStore) -> None:
    print("Unidades consumidoras configuradas:")
    for uc in store.iter_uc():
        print(f" - {uc.descricao} (ID: {uc.uid})")
    settings = store.settings
    pdf_label = "ativado" if settings.download_pdfs else "desativado"
    print(f"Download automático de PDFs: {pdf_label}")
    if settings.period_start or settings.period_end:
        print(
            "Filtro de período padrão: "
            f"{settings.period_start or '*'} até {settings.period_end or '*'}"
        )
    else:
        print("Filtro de período padrão: completo")


def _prompt_yes_no(message: str, *, default: bool | None = None) -> Optional[bool]:
    suffix = " [s/n]"
    if default is not None:
        suffix = f" [{'s' if default else 'n'}]"
    while True:
        answer = input(f"{message}{suffix}: ").strip().lower()
        if not answer and default is not None:
            return default
        if answer in {"s", "sim", "y", "yes"}:
            return True
        if answer in {"n", "nao", "não", "no"}:
            return False
        if not answer:
            return None
        print("Resposta inválida. Digite 's' ou 'n'.")


def _prompt_month(message: str, *, default: str | None = None) -> Optional[str]:
    pattern = re.compile(r"^\d{4}-\d{2}$")
    while True:
        answer = input(f"{message}: ").strip()
        if not answer:
            return default
        if pattern.match(answer):
            return answer
        print("Formato inválido. Use AAAA-MM ou deixe em branco.")


__all__ = ["run"]
