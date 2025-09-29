"""Utility functions for parsing and normalization."""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, Optional

LOGGER = logging.getLogger(__name__)


DECIMAL_RE = re.compile(r"[-+]?\d+[\d.,]*")
DATE_RE = re.compile(r"(\d{1,2})[\-/](\d{1,2})[\-/](\d{2,4})")
MONTH_RE = re.compile(r"(\d{1,2})[\-/](\d{2,4})")


def clean_number(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    return digits


def parse_decimal(value: Optional[str], places: Optional[int] = 2) -> Optional[Decimal]:
    if not value:
        return None
    normalized = value.replace("R$", "").replace(" ", "")
    normalized = normalized.replace(".", "").replace(",", ".")
    try:
        decimal_value = Decimal(normalized)
    except (InvalidOperation, ValueError) as exc:
        LOGGER.debug("Unable to parse decimal from %s: %s", value, exc)
        return None
    if places is None:
        return decimal_value
    quantizer = Decimal(1) / (Decimal(10) ** places)
    return decimal_value.quantize(quantizer, rounding=ROUND_HALF_UP)


def parse_month(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    match = MONTH_RE.search(value)
    if not match:
        return None
    month = int(match.group(1))
    year = match.group(2)
    if len(year) == 2:
        year = f"20{year}"
    return f"{month:02d}/{year}"


def parse_date(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    match = DATE_RE.search(value)
    if not match:
        return None
    day = int(match.group(1))
    month = int(match.group(2))
    year = match.group(3)
    if len(year) == 2:
        year = f"20{year}"
    try:
        parsed = datetime(int(year), month, day)
    except ValueError as exc:
        LOGGER.debug("Invalid date %s: %s", value, exc)
        return None
    return parsed.strftime("%d/%m/%Y")


def compute_invoice_hash(numero_instalacao: str, mes_referencia: str, valor_total: str) -> str:
    raw = f"{numero_instalacao}|{mes_referencia}|{valor_total}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def ensure_decimal_str(value: Optional[Decimal], places: int = 2) -> Optional[str]:
    if value is None:
        return None
    pattern = f"{{0:.{places}f}}"
    return pattern.format(value)


def decimal_to_string(value: Optional[Decimal]) -> Optional[str]:
    if value is None:
        return None
    normalized = value.normalize()
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def ensure_numeric(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    digits = clean_number(value)
    return digits or None


def validate_invoice(invoice: Dict[str, Any]) -> bool:
    """Perform basic validation checks."""

    valor_total = invoice.get("valor_total")
    consumo_kwh = invoice.get("consumo_kwh")
    mes_referencia = invoice.get("mes_referencia")
    vencimento = invoice.get("vencimento")

    try:
        if valor_total is not None and Decimal(str(valor_total)) <= 0:
            LOGGER.warning("Valor total inválido: %s", valor_total)
            return False
    except InvalidOperation:
        LOGGER.warning("Valor total não numérico: %s", valor_total)
        return False

    if consumo_kwh is not None:
        try:
            if Decimal(str(consumo_kwh)) < 0:
                LOGGER.warning("Consumo negativo: %s", consumo_kwh)
                return False
        except InvalidOperation:
            LOGGER.warning("Consumo não numérico: %s", consumo_kwh)
            return False

    if mes_referencia is None:
        LOGGER.warning("Mês de referência ausente")
        return False

    if vencimento is not None:
        parsed = parse_date(vencimento)
        if not parsed:
            LOGGER.warning("Data de vencimento inválida: %s", vencimento)
            return False
        invoice["vencimento"] = parsed

    # Reformat month to ensure normalization
    normalized_month = parse_month(mes_referencia)
    if not normalized_month:
        LOGGER.warning("Mês de referência inválido: %s", mes_referencia)
        return False
    invoice["mes_referencia"] = normalized_month

    decimal_fields = {
        "valor_total": 2,
        "tusd": 2,
        "te": 2,
        "icms": 2,
        "pis_cofins": 2,
        "valor_total_operacao": 2,
    }
    for key, places in decimal_fields.items():
        if invoice.get(key) is None:
            continue
        try:
            invoice[key] = ensure_decimal_str(Decimal(str(invoice[key])), places=places)
        except InvalidOperation:
            LOGGER.warning("Valor inválido para %s: %s", key, invoice.get(key))
            invoice[key] = None

    if invoice.get("tarifa_com_tributos") is not None:
        try:
            valor_tarifa = Decimal(str(invoice["tarifa_com_tributos"]))
            invoice["tarifa_com_tributos"] = ensure_decimal_str(valor_tarifa, places=5)
        except InvalidOperation:
            LOGGER.warning(
                "Tarifa com tributos inválida: %s", invoice.get("tarifa_com_tributos")
            )
            invoice["tarifa_com_tributos"] = None

    if invoice.get("consumo_kwh") is not None:
        try:
            invoice["consumo_kwh"] = str(Decimal(str(invoice["consumo_kwh"])))
        except InvalidOperation:
            invoice["consumo_kwh"] = None

    if invoice.get("quantidade_faturada") is not None:
        try:
            quantidade = Decimal(str(invoice["quantidade_faturada"]))
            if quantidade < 0:
                LOGGER.warning(
                    "Quantidade faturada negativa: %s", invoice["quantidade_faturada"]
                )
                return False
            invoice["quantidade_faturada"] = decimal_to_string(quantidade)
        except InvalidOperation:
            LOGGER.warning(
                "Quantidade faturada inválida: %s", invoice.get("quantidade_faturada")
            )
            invoice["quantidade_faturada"] = None

    return True


def merge_invoice_data(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    result = base.copy()
    for key, value in updates.items():
        if value not in (None, ""):
            result[key] = value
    return result


__all__ = [
    "parse_decimal",
    "parse_date",
    "parse_month",
    "compute_invoice_hash",
    "ensure_decimal_str",
    "ensure_numeric",
    "validate_invoice",
    "merge_invoice_data",
]
