import polars as pl

from src.database.models import InstitutionAlias, InstitutionMaster
from src.normalization_pipeline import apply_normalization, resolve_vendor_expressions

THRESHOLD = 90.0


def _make_institution(institution_id: int, canonical_name: str, aliases: list[str]) -> InstitutionMaster:
    institution = InstitutionMaster(institution_id=institution_id, canonical_name=canonical_name, active=True)
    institution.aliases = [
        InstitutionAlias(alias_text=text, alias_type="ALIAS", active=True) for text in aliases
    ]
    return institution


def _institutions():
    return [
        _make_institution(1, "NH농협은행", ["농협은행", "농은", "NH농협"]),
        _make_institution(2, "KB국민은행", ["국민은행", "KB국민"]),
    ]


def test_resolve_exact_alias_and_unresolved():
    texts = ["NH농협은행", "농은", "테스트전자"]
    results = resolve_vendor_expressions(texts, _institutions(), THRESHOLD)

    assert results["NH농협은행"]["normalization_method"] == "EXACT"
    assert results["농은"]["normalization_method"] == "ALIAS"
    assert results["테스트전자"]["normalization_method"] == "UNRESOLVED"
    assert results["테스트전자"]["review_status"] == "NEEDS_REVIEW"


def test_resolve_does_not_confirm_negative_examples():
    """OO농협/농협유통/NH투자는 FAST PATH만으로는 자동 확정되면 안 된다."""
    texts = ["OO농협", "농협유통", "NH투자"]
    results = resolve_vendor_expressions(texts, _institutions(), THRESHOLD)

    for text in texts:
        assert results[text]["normalization_method"] == "UNRESOLVED", text
        assert results[text]["canonical_institution"] is None, text


def test_apply_normalization_adds_columns_and_preserves_original():
    df = pl.DataFrame({"거래처": ["NH농협은행", "농은", "테스트전자"], "금액": [1000, 2000, 3000]})
    result = apply_normalization(df, "거래처", _institutions(), THRESHOLD)

    assert "거래처" in result.columns
    assert "금액" in result.columns
    assert "canonical_institution" in result.columns
    assert result.height == 3

    row = result.filter(pl.col("거래처") == "NH농협은행").to_dicts()[0]
    assert row["canonical_institution"] == "NH농협은행"
    assert row["normalization_method"] == "EXACT"


def test_apply_normalization_broadcasts_to_repeated_rows():
    df = pl.DataFrame({"거래처": ["농은", "농은", "농은"], "금액": [1, 2, 3]})
    result = apply_normalization(df, "거래처", _institutions(), THRESHOLD)

    assert result["canonical_institution"].unique().to_list() == ["NH농협은행"]
