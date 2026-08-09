import polars as pl
import pytest

from src.column_mapper import build_context_text, validate_mapping


def _sample_df():
    return pl.DataFrame(
        {
            "vendor_col": ["농협은행", "테스트전자"],
            "desc_col": ["대출이자 지급", "제품 판매대금"],
            "account_col": ["이자비용", "제품매출"],
        }
    )


def test_validate_mapping_missing_required():
    errors = validate_mapping({})
    assert any("거래처" in e for e in errors)


def test_validate_mapping_ok():
    errors = validate_mapping({"vendor": "vendor_col"})
    assert errors == []


def test_build_context_text_combines_mapped_columns():
    df = _sample_df()
    mapping = {"vendor": "vendor_col", "description": "desc_col", "account": "account_col"}
    result = build_context_text(df, mapping)
    assert result["context_text"][0] == "농협은행 | 대출이자 지급 | 이자비용"


def test_build_context_text_preserves_original_columns():
    df = _sample_df()
    mapping = {"vendor": "vendor_col"}
    result = build_context_text(df, mapping)
    assert "vendor_col" in result.columns
    assert "desc_col" in result.columns


def test_build_context_text_raises_without_required_field():
    df = _sample_df()
    with pytest.raises(ValueError):
        build_context_text(df, {"description": "desc_col"})
