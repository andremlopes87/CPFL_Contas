"""Persistence helpers for CPFL invoices."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd

from .utils import compute_invoice_hash

LOGGER = logging.getLogger(__name__)

MASTER_COLUMNS = [
    "cliente",
    "numero_instalacao",
    "numero_cliente",
    "mes_referencia",
    "vencimento",
    "valor_total",
    "consumo_kwh",
    "quantidade_faturada",
    "tarifa_com_tributos",
    "valor_total_operacao",
    "bandeira_tarifaria",
    "tusd",
    "te",
    "icms",
    "pis_cofins",
    "endereco_uc",
    "link_pdf",
    "hash_fatura",
    "status_pagamento",
    "arquivo_origem",
]


class MasterTable:
    def __init__(self, path: Path) -> None:
        self.path = path
        if self.path.exists():
            self.df = pd.read_csv(self.path, dtype=str)
        else:
            self.df = pd.DataFrame(columns=MASTER_COLUMNS)

    def lookup_hashes(self) -> set:
        hashes = set(self.df.get("hash_fatura", pd.Series(dtype=str)).dropna().tolist())
        return hashes

    def upsert_rows(self, rows: List[Dict[str, Optional[str]]]) -> Dict[str, int]:
        if not rows:
            return {"novas": 0, "atualizadas": 0, "ignoradas": 0}

        existing_hashes = self.lookup_hashes()
        new_rows = []
        updated_rows = 0
        ignored_rows = 0

        for row in rows:
            invoice_hash = row.get("hash_fatura")
            if not invoice_hash:
                continue
            mask = self.df["hash_fatura"] == invoice_hash
            if mask.any():
                index = self.df[mask].index[0]
                self.df.loc[index] = row
                updated_rows += 1
            elif invoice_hash not in existing_hashes:
                new_rows.append(row)
            else:
                ignored_rows += 1

        if new_rows:
            new_df = pd.DataFrame(new_rows)
            self.df = pd.concat([self.df, new_df], ignore_index=True)

        return {"novas": len(new_rows), "atualizadas": updated_rows, "ignoradas": ignored_rows}

    def save(self) -> None:
        self.df = self.df.sort_values(["cliente", "numero_instalacao", "mes_referencia"])
        self.df.to_csv(self.path, index=False)

    def save_excel(self, path: Path) -> None:
        self.df.to_excel(path, index=False)


class JsonWriter:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write(self, invoice: Dict[str, Optional[str]]) -> Path:
        invoice_hash = invoice.get("hash_fatura")
        filename = f"{invoice_hash}.json" if invoice_hash else "invoice.json"
        path = self.output_dir / filename
        with path.open("w", encoding="utf-8") as fp:
            json.dump(invoice, fp, ensure_ascii=False, indent=2)
        return path


def build_invoice_row(cliente: str, invoice: Dict[str, Optional[str]], source_file: Path) -> Dict[str, Optional[str]]:
    data = {column: None for column in MASTER_COLUMNS}
    data.update(invoice)
    data["cliente"] = cliente
    data["hash_fatura"] = compute_invoice_hash(
        invoice.get("numero_instalacao", ""),
        invoice.get("mes_referencia", ""),
        invoice.get("valor_total", "0"),
    )
    data["arquivo_origem"] = str(source_file)
    return data


def write_summary_log(summary: Dict[str, int]) -> str:
    return (
        f"Faturas novas: {summary.get('novas', 0)} | "
        f"Atualizadas: {summary.get('atualizadas', 0)} | "
        f"Ignoradas: {summary.get('ignoradas', 0)}"
    )


__all__ = ["MasterTable", "JsonWriter", "build_invoice_row", "write_summary_log", "MASTER_COLUMNS"]
