import polars as pl

from src.completeness_checker import (
    compare_completeness,
    get_institution_detail_rows,
    summarize_journal_by_institution,
)


def _company_result_df():
    return pl.DataFrame(
        {
            "institution_name": ["NH농협은행", "신한은행", "이상한기관"],
            "canonical_institution": ["NH농협은행", "신한은행", None],
            "review_status": ["AUTO", "AUTO", "NEEDS_REVIEW"],
        }
    )


def _journal_result_df():
    return pl.DataFrame(
        {
            "거래처": ["NH농협은행", "NH농협은행", "KB국민은행", "OO농협"],
            "canonical_institution": ["NH농협은행", "NH농협은행", "KB국민은행", "NH농협은행"],
            "review_status": ["AUTO", "AUTO", "AUTO", "NEEDS_REVIEW"],
            "금액": [1000, 2000, 3000, 4000],
        }
    )


def test_compare_completeness_finds_both_and_additional_candidates():
    result = compare_completeness(_company_result_df(), _journal_result_df(), "institution_name")

    assert result["both"] == ["NH농협은행"]
    assert result["additional_candidates"] == ["KB국민은행"]  # B - A
    assert result["company_only"] == ["신한은행"]  # A - B
    assert result["unidentified_in_company_list"] == ["이상한기관"]


def test_compare_completeness_excludes_needs_review_rows():
    """journal의 'OO농협'(NEEDS_REVIEW)은 canonical_institution이 NH농협은행이어도 B에 포함되면 안 된다."""
    result = compare_completeness(_company_result_df(), _journal_result_df(), "institution_name")
    # NH농협은행은 이미 AUTO 건으로 both에 들어가므로, OO농협의 NEEDS_REVIEW 건이
    # 추가되어도 셋 결과는 바뀌지 않아야 한다 (중복 집합 연산이므로).
    assert "NH농협은행" in result["both"]
    assert "NH농협은행" not in result["additional_candidates"]


def test_summarize_journal_by_institution_counts_and_sums_amount():
    summary = summarize_journal_by_institution(_journal_result_df(), ["NH농협은행", "KB국민은행"], amount_column="금액")
    rows = {r["canonical_institution"]: r for r in summary.to_dicts()}

    assert rows["NH농협은행"]["journal_count"] == 2
    assert rows["NH농협은행"]["total_amount"] == 3000
    assert rows["KB국민은행"]["journal_count"] == 1
    assert rows["KB국민은행"]["total_amount"] == 3000


def test_summarize_journal_by_institution_excludes_needs_review():
    """NH투자가 없는 목록에 OO농협의 NEEDS_REVIEW 건(NH농협은행 후보)이 섞여 들어가면 안 된다."""
    summary = summarize_journal_by_institution(_journal_result_df(), ["NH농협은행"], amount_column="금액")
    row = summary.to_dicts()[0]
    assert row["journal_count"] == 2  # OO농협(NEEDS_REVIEW) 건은 제외되어야 함


def test_get_institution_detail_rows_returns_only_confirmed_rows():
    detail = get_institution_detail_rows(_journal_result_df(), "NH농협은행", ["거래처", "금액", "review_status"])
    assert detail.height == 2
    assert set(detail["review_status"].to_list()) == {"AUTO"}
