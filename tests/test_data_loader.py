from pathlib import Path

from src.data_loader import load_journal_file


def test_load_journal_file_csv(tmp_path: Path):
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text("거래처,금액\n농협은행,1000\n테스트전자,2000\n", encoding="utf-8")

    df = load_journal_file(csv_path)

    assert df.height == 2
    assert "거래처" in df.columns


def test_load_journal_file_unsupported_extension(tmp_path: Path):
    bad_path = tmp_path / "sample.txt"
    bad_path.write_text("dummy", encoding="utf-8")

    try:
        load_journal_file(bad_path)
        assert False, "ValueError가 발생해야 합니다"
    except ValueError as e:
        assert "지원하지 않는" in str(e)
