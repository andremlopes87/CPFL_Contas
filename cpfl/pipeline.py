"""Main pipeline orchestration."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from .config import AppConfig, ClientConfig
from .pdf_parser import parse_pdf
from .storage import JsonWriter, MasterTable, build_invoice_row
from .utils import merge_invoice_data, validate_invoice

LOGGER = logging.getLogger(__name__)


@dataclass
class ProcessingResult:
    novas: int = 0
    atualizadas: int = 0
    ignoradas: int = 0


class InvoiceProcessor:
    def __init__(self, app_config: AppConfig, clients: List[ClientConfig]) -> None:
        self.app_config = app_config
        self.clients = clients
        self.master_table = MasterTable(app_config.master_table_path)
        self.json_writer = JsonWriter(app_config.json_output_dir)

    def run(self) -> ProcessingResult:
        summary = ProcessingResult()
        processed_rows: List[Dict[str, str]] = []

        for client in self.clients:
            client_dir = self._resolve_client_dir(client)
            if not client_dir.exists():
                LOGGER.warning("Pasta %s não existe para o cliente %s", client_dir, client.cliente)
                continue

            for pdf_file in sorted(client_dir.glob("*.pdf")):
                invoice = self._process_pdf(client, pdf_file)
                if invoice is None:
                    summary.ignoradas += 1
                    continue
                processed_rows.append(invoice)

        result = self.master_table.upsert_rows(processed_rows)
        summary.novas += result.get("novas", 0)
        summary.atualizadas += result.get("atualizadas", 0)
        summary.ignoradas += result.get("ignoradas", 0)

        self.master_table.save()
        self.master_table.save_excel(self.app_config.master_excel_path)

        return summary

    def _resolve_client_dir(self, client: ClientConfig) -> Path:
        if client.pasta_entrada:
            return Path(client.pasta_entrada)
        return self.app_config.inbox_dir / client.slug

    def _process_pdf(self, client: ClientConfig, pdf_path: Path) -> Dict[str, str] | None:
        LOGGER.info("Processando %s para cliente %s", pdf_path, client.cliente)
        parsed = parse_pdf(pdf_path)

        invoice_data = merge_invoice_data({}, parsed.raw)
        invoice_data["numero_instalacao"] = invoice_data.get("numero_instalacao") or client.numero_instalacao
        invoice_data["numero_cliente"] = invoice_data.get("numero_cliente") or client.numero_cliente

        if not validate_invoice(invoice_data):
            LOGGER.error("Fatura %s não passou na validação", pdf_path)
            return None

        destination = self._archive_file(pdf_path)
        invoice_row = build_invoice_row(client.cliente, invoice_data, destination)
        self.json_writer.write(invoice_row)
        return invoice_row

    def _archive_file(self, pdf_path: Path) -> Path:
        archive_dir = self.app_config.archive_dir
        archive_dir.mkdir(parents=True, exist_ok=True)
        destination = archive_dir / pdf_path.name
        if destination.exists():
            counter = 1
            while True:
                candidate = archive_dir / f"{pdf_path.stem}_dup{counter}{pdf_path.suffix}"
                if not candidate.exists():
                    destination = candidate
                    break
                counter += 1
        pdf_path.rename(destination)
        LOGGER.info("Arquivo %s arquivado em %s", pdf_path, destination)
        return destination


__all__ = ["InvoiceProcessor", "ProcessingResult"]
