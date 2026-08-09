import polars as pl
import pytest

from src.human_review import apply_human_decision


def _sample_df():
    return pl.DataFrame(
        {
            "detected_expression": ["농협", "농협", "테스트전자"],
            "context_text": ["농협 | 농산물 구매 | 원재료 | 외상매입금", "농협 | 대출이자 | 이자비용 | 장기차입금", "테스트전자 | 판매 | 제품매출 | 보통예금"],
            "canonical_institution": [None, "NH농협은행", None],
            "institution_id": [None, 1, None],
            "normalization_method": ["UNRESOLVED", "FUZZY", "UNRESOLVED"],
            "review_status": ["NEEDS_REVIEW", "NEEDS_REVIEW", "NEEDS_REVIEW"],
            "user_confirmed": [False, False, False],
        }
    )


def test_approve_confirms_only_matching_row():
    df = _sample_df()
    result = apply_human_decision(
        df,
        {"detected_expression": "농협", "context_text": "농협 | 대출이자 | 이자비용 | 장기차입금"},
        "APPROVE",
    )
    row = result.filter(pl.col("context_text") == "농협 | 대출이자 | 이자비용 | 장기차입금").to_dicts()[0]
    assert row["review_status"] == "AUTO"
    assert row["normalization_method"] == "HUMAN"
    assert row["user_confirmed"] is True

    other_row = result.filter(pl.col("detected_expression") == "테스트전자").to_dicts()[0]
    assert other_row["review_status"] == "NEEDS_REVIEW"
    assert other_row["user_confirmed"] is False


def test_change_institution_overrides_canonical_name():
    df = _sample_df()
    result = apply_human_decision(
        df,
        {"detected_expression": "농협", "context_text": "농협 | 농산물 구매 | 원재료 | 외상매입금"},
        "CHANGE_INSTITUTION",
        override_institution=(2, "KB국민은행"),
    )
    row = result.filter(pl.col("context_text") == "농협 | 농산물 구매 | 원재료 | 외상매입금").to_dicts()[0]
    assert row["canonical_institution"] == "KB국민은행"
    assert row["institution_id"] == 2
    assert row["review_status"] == "AUTO"


def test_not_financial_institution_clears_institution():
    df = _sample_df()
    result = apply_human_decision(df, {"detected_expression": "테스트전자"}, "NOT_FINANCIAL_INSTITUTION")
    row = result.filter(pl.col("detected_expression") == "테스트전자").to_dicts()[0]
    assert row["review_status"] == "NOT_FINANCIAL_INSTITUTION"
    assert row["canonical_institution"] is None


def test_hold_keeps_institution_but_marks_hold():
    df = _sample_df()
    result = apply_human_decision(
        df,
        {"detected_expression": "농협", "context_text": "농협 | 대출이자 | 이자비용 | 장기차입금"},
        "HOLD",
    )
    row = result.filter(pl.col("context_text") == "농협 | 대출이자 | 이자비용 | 장기차입금").to_dicts()[0]
    assert row["review_status"] == "HOLD"
    assert row["canonical_institution"] == "NH농협은행"


def test_change_institution_without_override_raises():
    with pytest.raises(ValueError):
        apply_human_decision(_sample_df(), {"detected_expression": "농협"}, "CHANGE_INSTITUTION")


def test_unknown_action_raises():
    with pytest.raises(ValueError):
        apply_human_decision(_sample_df(), {"detected_expression": "농협"}, "NOT_A_REAL_ACTION")
