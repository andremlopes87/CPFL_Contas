from __future__ import annotations

import json
from pathlib import Path

from cpfl.parser import export_csv, parse_paid_history, parse_status_history


def load_fixture(name: str) -> dict:
    base = Path(__file__).parent / "mocks"
    return json.loads((base / name).read_text(encoding="utf-8"))


def test_parse_paid_history(tmp_path):
    payload = load_fixture("raw_contas_quitadas_UC.json")
    records = parse_paid_history(payload, "uc_teste")
    assert len(records) == 2

    first = records[0]
    assert first.mes_referencia == "2024-01"
    assert first.vencimento == "2024-02-05"
    assert first.valor == "123.45"
    assert first.conta_id == "202401123"
    assert "historico-contas" in first.pdf_hints[0]

    csv_path = tmp_path / "paid.csv"
    export_csv(records, csv_path)
    content = csv_path.read_text(encoding="utf-8")
    assert "2024-02-05" in content
    assert "quitada" in content


def test_parse_status_history(tmp_path):
    payload = load_fixture("raw_validar_situacao_UC.json")
    records = parse_status_history(payload, "uc_teste")
    assert len(records) == 1
    record = records[0]
    assert record.mes_referencia == "2024-03"
    assert record.vencimento == "2024-04-10"
    assert record.status.lower() == "em aberto"

    csv_path = tmp_path / "status.csv"
    export_csv(records, csv_path)
    content = csv_path.read_text(encoding="utf-8")
    assert "aberta" in content
    assert "202403777" in content
