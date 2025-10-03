from __future__ import annotations

from pathlib import Path

from cpfl import cli


def test_dry_run(tmp_path: Path):
    samples = Path(__file__).parent / "mocks"
    exit_code = cli.main(["dry-run", "--samples", str(samples), "--output", str(tmp_path)])
    assert exit_code == 0
    csv_path = tmp_path / "faturas.csv"
    assert csv_path.exists()
    content = csv_path.read_text(encoding="utf-8")
    assert "quitada" in content
    assert "aberta" in content
