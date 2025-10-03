"""Command line interface for the CPFL collector."""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional

from .config import ConfigStore, GlobalSettings, UCConfig, DEFAULT_CONFIG_PATH
from .cpfl_client import AuthorizationError, CPFLClient, CPFLAPIError
from .onboarding import ensure_config
from .parser import InvoiceRecord, export_csv, parse_paid_history, parse_status_history
from .utils import BookmarkletServer, ensure_directory, safe_write_json, setup_logging, slugify

LOGGER = logging.getLogger("cpfl.cli")


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    setup_logging(args.log_level)

    if args.command == "run":
        return _command_run(args)
    if args.command == "dry-run":
        return _command_dry_run(args)
    if args.command == "inspect-har":
        return _command_inspect_har(args)
    if args.command == "bookmarklet":
        return _command_bookmarklet(args)

    parser.print_help()
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Coletor CPFL Energia via HTTP")
    parser.add_argument("--log-level", default="INFO", help="Nível de log (DEBUG, INFO, WARNING, ERROR)")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Executa coleta real usando config.json")
    run_parser.add_argument("--config", type=Path, default=None, help="Arquivo de configuração config.json")
    run_parser.add_argument(
        "--download-pdfs",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Força habilitar ou desabilitar o download de PDFs",
    )
    run_parser.add_argument("--period-start", default=None, help="Filtro opcional por mês inicial (AAAA-MM)")
    run_parser.add_argument("--period-end", default=None, help="Filtro opcional por mês final (AAAA-MM)")
    run_parser.add_argument("--bookmarklet-timeout", type=int, default=180, help="Tempo limite esperando tokens do bookmarklet")

    dry_parser = subparsers.add_parser("dry-run", help="Executa parsing com os mocks inclusos")
    dry_parser.add_argument("--samples", type=Path, default=Path("data/mocks"), help="Diretório com JSONs de exemplo")
    dry_parser.add_argument("--output", type=Path, default=Path("out"), help="Diretório de saída para a simulação")

    har_parser = subparsers.add_parser("inspect-har", help="Sugere endpoints a partir de um arquivo HAR")
    har_parser.add_argument("har", type=Path, help="Arquivo .har exportado do navegador")

    subparsers.add_parser("bookmarklet", help="Mostra o bookmarklet usado para capturar tokens")

    return parser


def _command_run(args: argparse.Namespace) -> int:
    return run_collector(
        args.config,
        download_pdfs=args.download_pdfs,
        period_start=args.period_start,
        period_end=args.period_end,
        bookmarklet_timeout=args.bookmarklet_timeout,
        allow_onboarding=False,
    )


def run_collector(
    config_path: Path | None = None,
    *,
    download_pdfs: Optional[bool] = None,
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
    bookmarklet_timeout: int = 180,
    allow_onboarding: bool = False,
) -> int:
    resolved_path = (config_path or DEFAULT_CONFIG_PATH).expanduser()
    if allow_onboarding:
        resolved_path = ensure_config(resolved_path)
    try:
        store = ConfigStore(resolved_path)
    except FileNotFoundError:
        LOGGER.error(
            "Arquivo de configuração %s não encontrado. Execute o onboarding ou informe --config.",
            resolved_path,
        )
        return 2
    except Exception as exc:  # pragma: no cover - erro de configuração
        LOGGER.error("Erro carregando config: %s", exc)
        return 2

    settings = store.settings
    if download_pdfs is not None:
        settings.download_pdfs = bool(download_pdfs)
    if period_start:
        settings.period_start = period_start
    if period_end:
        settings.period_end = period_end

    all_records: List[InvoiceRecord] = []
    for uc in store.iter_uc():
        LOGGER.info("Processando UC %s (%s)", uc.uid, uc.descricao)
        try:
            records = _process_uc(store, settings, uc, bookmarklet_timeout)
            all_records.extend(records)
        except AuthorizationError as exc:
            LOGGER.error(
                "Autorização falhou para UC %s: %s. Revise tokens/refresh ou execute o bookmarklet.",
                uc.uid,
                exc,
            )
        except CPFLAPIError as exc:
            LOGGER.error("Falha na UC %s: %s", uc.uid, exc)
    if not all_records:
        LOGGER.warning(
            "Nenhuma fatura coletada. Verifique se o handshake retornou dados e se os payloads estão corretos."
        )
        return 1

    csv_path = settings.output_dir / "faturas.csv"
    export_csv(all_records, csv_path)
    LOGGER.info("CSV consolidado disponível em %s", csv_path)
    return 0


def _process_uc(
    store: ConfigStore,
    settings: GlobalSettings,
    uc: UCConfig,
    bookmarklet_timeout: int,
) -> List[InvoiceRecord]:
    client = CPFLClient(settings, uc)
    success, bundle = client.ensure_authenticated()
    if not success:
        LOGGER.warning("Token atual/refresh falhou. Iniciando fluxo do bookmarklet para %s", uc.uid)
        bundle = client.capture_tokens_via_bookmarklet(timeout=bookmarklet_timeout)
        if not bundle:
            raise AuthorizationError("Não foi possível obter tokens via bookmarklet")
        client.update_tokens(bundle)
        store.update_tokens(uc.uid, access_token=bundle.access_token, refresh_token=bundle.refresh_token, expires_at=bundle.expires_at, key=uc.key)
    elif bundle:
        store.update_tokens(uc.uid, access_token=bundle.access_token, refresh_token=bundle.refresh_token, expires_at=bundle.expires_at, key=uc.key)

    handshake_payload = client.handshake()
    paid_payload = client.fetch_paid_history()
    status_payload = client.fetch_status_history()

    json_output = settings.output_dir / "json" / uc.slug
    ensure_directory(json_output)
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    safe_write_json(json_output / f"{timestamp}_validar_integracao.json", handshake_payload)
    safe_write_json(json_output / f"{timestamp}_contas_quitadas.json", paid_payload)
    safe_write_json(json_output / f"{timestamp}_validar_situacao.json", status_payload)

    paid_records = parse_paid_history(paid_payload, uc.slug)
    status_records = parse_status_history(status_payload, uc.slug)

    records: List[InvoiceRecord] = paid_records + status_records
    if settings.period_start or settings.period_end:
        records = [record for record in records if _filter_record(record, settings.period_start, settings.period_end)]

    if settings.download_pdfs:
        _download_pdfs(client, settings, uc, records)

    return records


def _filter_record(record: InvoiceRecord, period_start: Optional[str], period_end: Optional[str]) -> bool:
    month = record.mes_referencia or ""
    if period_start and month and month < period_start:
        return False
    if period_end and month and month > period_end:
        return False
    return True


def _download_pdfs(
    client: CPFLClient,
    settings: GlobalSettings,
    uc: UCConfig,
    records: Iterable[InvoiceRecord],
) -> None:
    download_dir = settings.output_dir / "downloads" / uc.slug
    for record in records:
        if not getattr(record, "pdf_hints", None):
            continue
        for index, hint in enumerate(record.pdf_hints, start=1):
            filename = f"{record.mes_referencia or record.conta_id or index}.pdf"
            target = download_dir / filename
            try:
                client.download_pdf(hint, target)
            except CPFLAPIError:
                LOGGER.debug("Não foi possível baixar PDF em %s", hint)


def _command_dry_run(args: argparse.Namespace) -> int:
    samples_dir = args.samples
    paid_path = samples_dir / "raw_contas_quitadas_UC.json"
    status_path = samples_dir / "raw_validar_situacao_UC.json"
    if not paid_path.exists() or not status_path.exists():
        LOGGER.error("Mocks não encontrados em %s", samples_dir)
        return 2

    paid_payload = json.loads(paid_path.read_text(encoding="utf-8"))
    status_payload = json.loads(status_path.read_text(encoding="utf-8"))

    uc_slug = slugify("UC-MOCK")
    records = parse_paid_history(paid_payload, uc_slug) + parse_status_history(status_payload, uc_slug)
    export_dir = args.output
    export_dir.mkdir(parents=True, exist_ok=True)
    export_csv(records, export_dir / "faturas.csv")
    LOGGER.info("Dry-run concluído. Arquivos em %s", export_dir)
    return 0


def _command_inspect_har(args: argparse.Namespace) -> int:
    har_path = args.har
    if not har_path.exists():
        LOGGER.error("Arquivo HAR %s não encontrado", har_path)
        return 2
    try:
        har_data = json.loads(har_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        LOGGER.error("HAR inválido: %s", exc)
        return 2

    entries = har_data.get("log", {}).get("entries", [])
    endpoints = set()
    headers = set()
    for entry in entries:
        request = entry.get("request", {})
        url = request.get("url", "")
        if "agencia-webapi" in url:
            endpoints.add(url)
            for header in request.get("headers", []):
                name = header.get("name", "").lower()
                if name.startswith("x-") or name in {"authorization", "clientid"}:
                    headers.add(f"{name}: {header.get('value', '')}")
    LOGGER.info("Endpoints encontrados:")
    for endpoint in sorted(endpoints):
        LOGGER.info("  %s", endpoint)
    LOGGER.info("Headers relevantes:")
    for header in sorted(headers):
        LOGGER.info("  %s", header)
    return 0


def _command_bookmarklet(args: argparse.Namespace) -> int:
    server = BookmarkletServer()
    print(server.bookmarklet_snippet)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
