"""Command line runner for CPFL invoice processing."""
from __future__ import annotations

import argparse
import logging
import sys

from cpfl.config import load_clients, resolve_app_config
from cpfl.pipeline import InvoiceProcessor

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format=LOG_FORMAT)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Processa faturas da CPFL a partir de PDFs.")
    parser.add_argument("command", choices=["sync"], help="Comando a executar.")
    parser.add_argument("--config", dest="config", help="Caminho do arquivo de configuração de clientes.")
    parser.add_argument("--verbose", action="store_true", help="Habilita logs detalhados.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(args.verbose)

    if args.command != "sync":
        raise ValueError("Comando desconhecido. Use 'sync'.")

    app_config = resolve_app_config(args.config)
    clients = load_clients(app_config.config_path)

    processor = InvoiceProcessor(app_config, clients)
    summary = processor.run()

    logging.info(
        "Resumo: novas=%s atualizadas=%s ignoradas=%s",
        summary.novas,
        summary.atualizadas,
        summary.ignoradas,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
