"""PDF parsing logic for CPFL invoices."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional

import pdfplumber

from .utils import (
    decimal_to_string,
    ensure_decimal_str,
    ensure_numeric,
    parse_decimal,
    parse_date,
    parse_month,
)

LOGGER = logging.getLogger(__name__)


@dataclass
class ParsedInvoice:
    text: str
    raw: Dict[str, Optional[str]]


FIELD_PATTERNS: Dict[str, Iterable[re.Pattern[str]]] = {
    "numero_instalacao": (
        re.compile(r"instala[çc][aã]o[:\s]*([\d.]+)", re.I),
        re.compile(r"n[úu]mero\s+da\s+instala[çc][aã]o[:\s]*([\d.]+)", re.I),
    ),
    "numero_cliente": (
        re.compile(r"n[úu]mero\s+do\s+cliente[:\s]*([\d.]+)", re.I),
        re.compile(r"c[óo]digo\s+do\s+cliente[:\s]*([\d.]+)", re.I),
    ),
    "mes_referencia": (
        re.compile(r"conta\s*/?\s*m[eê]s[:\s]*([0-9/\-]+)", re.I),
        re.compile(r"refer[êe]ncia[:\s]*([0-9/\-]+)", re.I),
    ),
    "vencimento": (
        re.compile(r"vencimento[:\s]*([\d/\-]+)", re.I),
        re.compile(r"data\s+de\s+vencimento[:\s]*([\d/\-]+)", re.I),
    ),
    "valor_total": (
        re.compile(r"total\s+a\s+pagar[:\s]*(?:r\$\s*)?([\d.,]+)", re.I),
        re.compile(r"valor\s+total\s+da\s+conta[:\s]*(?:r\$\s*)?([\d.,]+)", re.I),
    ),
    "consumo_kwh": (
        re.compile(r"consumo.*?([\d.,]+)\s*kwh", re.I),
        re.compile(r"quant\.?\s*consumida[:\s]*([\d.,]+)", re.I),
    ),
    "quantidade_faturada": (
        re.compile(r"quant\.?\s*faturad[ao][:\s]*([\d.,]+)", re.I),
    ),
    "tarifa_com_tributos": (
        re.compile(r"tarifa\s+com\s+tributos[:\s]*(?:r\$\s*)?([\d.,]+)", re.I),
    ),
    "valor_total_operacao": (
        re.compile(r"valor\s+total\s+da\s+opera[cç][aã]o[:\s]*(?:r\$\s*)?([\d.,]+)", re.I),
    ),
    "bandeira_tarifaria": (
        re.compile(r"bandeira\s+tarif[áa]ria[:\s]*([\w ]+)", re.I),
    ),
    "tusd": (
        re.compile(r"tusd[:\s]*([\d.,]+)", re.I),
    ),
    "te": (
        re.compile(r"t[eé][\s:]*([\d.,]+)", re.I),
    ),
    "icms": (
        re.compile(r"icms[:\s]*([\d.,]+)", re.I),
    ),
    "pis_cofins": (
        re.compile(r"pis\/?cofins[:\s]*([\d.,]+)", re.I),
    ),
    "endereco_uc": (
        re.compile(r"endere[çc]o\s+da\s+unidade\s+consumidora[:\s]*(.+)", re.I),
    ),
    "status_pagamento": (
        re.compile(r"status\s+do\s+pagamento[:\s]*(.+)", re.I),
    ),
    "link_pdf": (
        re.compile(r"https?://\S+", re.I),
    ),
}


def extract_text(pdf_path: Path) -> str:
    text_segments = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            text_segments.append(text)
    return "\n".join(text_segments)


def parse_pdf(pdf_path: Path) -> ParsedInvoice:
    LOGGER.info("Lendo PDF %s", pdf_path)
    text = extract_text(pdf_path)
    raw: Dict[str, Optional[str]] = {key: None for key in FIELD_PATTERNS}

    for field, patterns in FIELD_PATTERNS.items():
        for pattern in patterns:
            matches = pattern.findall(text)
            if not matches:
                continue
            value = matches[-1]
            if isinstance(value, tuple):
                value = value[0]
            raw[field] = value.strip()
            break

    # Fallback for endereco: may span multiple lines
    if not raw.get("endereco_uc"):
        endereco_match = re.search(
            r"endereço\s+da\s+unidade\s+consumidora[:\s]*(.+?)(?:\n\s*\n|status|valor total)",
            text,
            re.I | re.S,
        )
        if endereco_match:
            raw["endereco_uc"] = re.sub(r"\s+", " ", endereco_match.group(1).strip())

    processed: Dict[str, Optional[str]] = {}

    processed["numero_instalacao"] = ensure_numeric(raw.get("numero_instalacao"))
    processed["numero_cliente"] = ensure_numeric(raw.get("numero_cliente"))
    processed["mes_referencia"] = parse_month(raw.get("mes_referencia")) or raw.get("mes_referencia")
    processed["vencimento"] = parse_date(raw.get("vencimento")) or raw.get("vencimento")

    for money_key in ("valor_total", "tusd", "te", "icms", "pis_cofins", "valor_total_operacao"):
        value = parse_decimal(raw.get(money_key))
        processed[money_key] = (
            ensure_decimal_str(value) if value is not None else None
        )

    tarifa_valor = parse_decimal(raw.get("tarifa_com_tributos"), places=5)
    processed["tarifa_com_tributos"] = (
        ensure_decimal_str(tarifa_valor, places=5) if tarifa_valor is not None else None
    )

    processed["consumo_kwh"] = raw.get("consumo_kwh")
    if processed["consumo_kwh"]:
        processed["consumo_kwh"] = processed["consumo_kwh"].replace(",", ".")

    quantidade = parse_decimal(raw.get("quantidade_faturada"), places=None)
    processed["quantidade_faturada"] = (
        decimal_to_string(quantidade) if quantidade is not None else None
    )

    processed["bandeira_tarifaria"] = raw.get("bandeira_tarifaria")
    processed["endereco_uc"] = raw.get("endereco_uc")
    processed["link_pdf"] = raw.get("link_pdf")
    processed["status_pagamento"] = raw.get("status_pagamento")

    return ParsedInvoice(text=text, raw=processed)


__all__ = ["parse_pdf", "ParsedInvoice"]
