"""Parsing helpers to normalize CPFL invoice payloads."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import pandas as pd
from dateutil import parser as date_parser

LOGGER = logging.getLogger("cpfl.parser")


MONTH_KEYS = {
    "mesreferencia",
    "mesref",
    "mescompetencia",
    "mes",
    "mesreferecia",
    "competencia",
}

DUE_KEYS = {
    "datavencimento",
    "vencimento",
    "data_vencimento",
    "datavcto",
    "dataultimovencimento",
}

VALUE_KEYS = {
    "valor",
    "valorfatura",
    "valorconta",
    "valortotal",
    "valor_total",
    "valordocumento",
}

CONSUMPTION_KEYS = {
    "consumo",
    "consumokwh",
    "quantidade",
    "quantidadefaturada",
    "kwh",
}

ACCOUNT_KEYS = {
    "numerodocumento",
    "numeroconta",
    "contaid",
    "conta",
    "idconta",
    "documentoid",
    "numerofatura",
}

STATUS_KEYS = {
    "situacao",
    "status",
    "statuspagamento",
    "statusfatura",
    "descricao",
}

INSTALACAO_KEYS = {"instalacaoreal", "instalacao", "instalacaofisica"}
DOCUMENT_KEYS = {"documento", "cpfcnpj", "cpf", "cnpj"}
PDF_KEYS = {"pdf", "link", "url", "arquivo", "documento"}


@dataclass
class InvoiceRecord:
    uc: str
    tipo: str
    mes_referencia: Optional[str]
    vencimento: Optional[str]
    valor: Optional[str]
    consumo_kwh: Optional[str]
    conta_id: Optional[str]
    status: Optional[str]
    instalacao_real: Optional[str]
    documento: Optional[str]
    extras: Dict[str, Any] = field(default_factory=dict)
    pdf_hints: List[str] = field(default_factory=list)

    def to_row(self) -> Dict[str, Any]:
        row = {
            "_uc": self.uc,
            "_tipo": self.tipo,
            "mes_referencia": self.mes_referencia or "",
            "vencimento": self.vencimento or "",
            "valor": self.valor or "",
            "consumo_kwh": self.consumo_kwh or "",
            "conta_id": self.conta_id or "",
            "status": self.status or "",
            "instalacao_real": self.instalacao_real or "",
            "documento": self.documento or "",
        }
        for key, value in sorted(self.extras.items()):
            row[f"extra_{key}"] = value
        if self.pdf_hints:
            row["pdf_hint"] = "|".join(self.pdf_hints)
        return row


def parse_paid_history(payload: Dict[str, Any], uc: str) -> List[InvoiceRecord]:
    return _parse_generic_history(payload, uc, "quitada")


def parse_status_history(payload: Dict[str, Any], uc: str) -> List[InvoiceRecord]:
    return _parse_generic_history(payload, uc, "aberta")


# ---------------------------------------------------------------------------

def _parse_generic_history(payload: Dict[str, Any], uc: str, tipo: str) -> List[InvoiceRecord]:
    records: List[InvoiceRecord] = []
    for block in _iter_invoice_blocks(payload):
        for raw_invoice in block:
            record = _build_record(raw_invoice, uc, tipo)
            if record:
                records.append(record)
    LOGGER.info("Extraídas %s faturas do payload %s/%s", len(records), uc, tipo)
    return records


def _iter_invoice_blocks(payload: Any) -> Iterable[List[Dict[str, Any]]]:
    seen: set[int] = set()
    stack: List[Any] = [payload]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for value in current.values():
                stack.append(value)
        elif isinstance(current, list):
            if current and all(isinstance(item, dict) for item in current):
                if _list_contains_invoice(current):
                    identifier = id(current)
                    if identifier not in seen:
                        seen.add(identifier)
                        yield current
                    continue
            stack.extend(current)


def _list_contains_invoice(items: Sequence[Dict[str, Any]]) -> bool:
    for item in items:
        if _dict_looks_like_invoice(item):
            return True
    return False


def _dict_looks_like_invoice(item: Dict[str, Any]) -> bool:
    keys = {_normalize_key(key) for key in item.keys()}
    if keys & MONTH_KEYS:
        return True
    if keys & DUE_KEYS:
        return True
    if keys & VALUE_KEYS:
        return True
    if keys & ACCOUNT_KEYS:
        return True
    for value in item.values():
        if isinstance(value, dict) and _dict_looks_like_invoice(value):
            return True
    return False


def _build_record(item: Dict[str, Any], uc: str, tipo: str) -> Optional[InvoiceRecord]:
    mes = _normalize_month(_find_value(item, MONTH_KEYS))
    vencimento = _normalize_date(_find_value(item, DUE_KEYS))
    valor = _normalize_decimal(_find_value(item, VALUE_KEYS))
    consumo = _normalize_consumption(_find_value(item, CONSUMPTION_KEYS))
    conta = _stringify(_find_value(item, ACCOUNT_KEYS))
    status = _stringify(_find_value(item, STATUS_KEYS))
    instalacao_real = _stringify(_find_value(item, INSTALACAO_KEYS))
    documento = _stringify(_find_value(item, DOCUMENT_KEYS))
    extras = _collect_extras(item)
    pdf_hints = _collect_pdf_hints(item)

    if not any([mes, vencimento, valor, conta]):
        LOGGER.debug("Bloco ignorado por não parecer fatura: %s", item)
        return None

    return InvoiceRecord(
        uc=uc,
        tipo=tipo,
        mes_referencia=mes,
        vencimento=vencimento,
        valor=valor,
        consumo_kwh=consumo,
        conta_id=conta,
        status=status,
        instalacao_real=instalacao_real,
        documento=documento,
        extras=extras,
        pdf_hints=pdf_hints,
    )


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _find_value(item: Any, keyset: Iterable[str]) -> Any:
    normalized_keys = set(keyset)
    queue: List[Any] = [item]
    while queue:
        current = queue.pop(0)
        if isinstance(current, dict):
            for key, value in current.items():
                if _normalize_key(key) in normalized_keys:
                    if isinstance(value, (dict, list)):
                        inner = _extract_text_from_nested(value)
                        if inner is not None:
                            return inner
                    return value
                queue.append(value)
        elif isinstance(current, list):
            queue.extend(current)
    return None


def _extract_text_from_nested(value: Any) -> Optional[str]:
    if isinstance(value, (str, int, float)):
        return str(value)
    if isinstance(value, list):
        for element in value:
            extracted = _extract_text_from_nested(element)
            if extracted:
                return extracted
    if isinstance(value, dict):
        for element in value.values():
            extracted = _extract_text_from_nested(element)
            if extracted:
                return extracted
    return None


def _normalize_month(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("\\u00a0", " ").replace("Mes ", "")
    match = re.search(r"(\d{4})[-/](\d{1,2})", text)
    if match:
        year = int(match.group(1))
        month = int(match.group(2))
        return f"{year:04d}-{month:02d}"
    match = re.search(r"(\d{1,2})[/.-](\d{4})", text)
    if match:
        month = int(match.group(1))
        year = int(match.group(2))
        return f"{year:04d}-{month:02d}"
    match = re.search(r"(\d{2})(\d{4})", text)
    if match:
        month = int(match.group(1))
        year = int(match.group(2))
        return f"{year:04d}-{month:02d}"
    try:
        parsed = date_parser.parse(text, dayfirst=False, fuzzy=True, default=datetime(2000, 1, 1))
        return f"{parsed.year:04d}-{parsed.month:02d}"
    except (ValueError, OverflowError):
        LOGGER.debug("Não foi possível normalizar mês: %s", text)
        return None


def _normalize_date(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}", text):
            parsed = date_parser.parse(text, dayfirst=False)
        else:
            parsed = date_parser.parse(text, dayfirst=True, fuzzy=True)
        return parsed.date().isoformat()
    except (ValueError, OverflowError):
        LOGGER.debug("Não foi possível normalizar data: %s", text)
        return None


def _normalize_decimal(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        decimal_value = Decimal(str(value))
    else:
        text = str(value)
        text = text.replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".")
        try:
            decimal_value = Decimal(text)
        except (InvalidOperation, ValueError):
            LOGGER.debug("Valor não numérico: %s", value)
            return None
    quantized = decimal_value.quantize(Decimal("0.01"))
    return format(quantized, "f")


def _normalize_consumption(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        decimal_value = Decimal(str(value).replace(",", "."))
        if decimal_value == decimal_value.to_integral_value():
            return str(int(decimal_value))
        return format(decimal_value.normalize(), "f")
    except (InvalidOperation, ValueError):
        return None


def _stringify(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _collect_extras(item: Dict[str, Any]) -> Dict[str, Any]:
    extras: Dict[str, Any] = {}
    for key in ["NumeroCliente", "ParceiroNegocio", "ContaContrato"]:
        value = _find_value(item, {_normalize_key(key)})
        if value:
            extras[_normalize_key(key)] = str(value)
    return extras


def _collect_pdf_hints(item: Dict[str, Any]) -> List[str]:
    hints: List[str] = []
    stack: List[Any] = [item]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key, value in current.items():
                norm_key = _normalize_key(key)
                if norm_key in PDF_KEYS and isinstance(value, str) and "pdf" in value.lower():
                    hints.append(value)
                stack.append(value)
        elif isinstance(current, list):
            stack.extend(current)
        elif isinstance(current, str) and "pdf" in current.lower():
            hints.append(current)
    return sorted(set(hints))


def export_csv(records: Iterable[InvoiceRecord], target: Path) -> None:
    rows = [record.to_row() for record in records]
    if not rows:
        LOGGER.warning("Nenhuma fatura para exportar em %s", target)
        target.write_text("", encoding="utf-8")
        return

    keys = list(rows[0].keys())
    for row in rows[1:]:
        for key in row.keys():
            if key not in keys:
                keys.append(key)

    df = pd.DataFrame(rows)
    missing_cols = [key for key in keys if key not in df.columns]
    for col in missing_cols:
        df[col] = ""
    df = df[keys]
    df = df.sort_values(by=["_uc", "vencimento", "_tipo"], kind="stable")

    target.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(target, index=False, encoding="utf-8-sig")


__all__ = [
    "InvoiceRecord",
    "parse_paid_history",
    "parse_status_history",
    "export_csv",
]
