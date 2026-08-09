import polars as pl
import pytest

from src.export_service import build_excel_report


def test_build_excel_report_returns_nonempty_bytes():
    sheets = {
        "Normalized_Journal": pl.DataFrame({"거래처": ["NH농협은행"], "canonical_institution": ["NH농협은행"]}),
        "Manual_Review": pl.DataFrame({"거래처": ["OO농협"], "review_status": ["NEEDS_REVIEW"]}),
    }
    data = build_excel_report(sheets)
    assert isinstance(data, bytes)
    assert len(data) > 0
    assert data[:2] == b"PK"  # xlsx는 zip 포맷이라 PK 시그니처로 시작한다


def test_build_excel_report_handles_empty_dataframe():
    sheets = {"Additional_Candidates": pl.DataFrame({"canonical_institution": []}, schema={"canonical_institution": pl.Utf8})}
    data = build_excel_report(sheets)
    assert isinstance(data, bytes)
    assert len(data) > 0


def test_build_excel_report_truncates_long_sheet_names():
    long_name = "이건_31자를_훨씬_넘는_매우_긴_시트_이름_테스트용_문자열"
    sheets = {long_name: pl.DataFrame({"a": [1]})}
    data = build_excel_report(sheets)  # 예외 없이 성공해야 한다
    assert len(data) > 0


def test_build_excel_report_raises_on_no_sheets():
    with pytest.raises(ValueError):
        build_excel_report({})
