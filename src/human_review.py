"""Human-in-the-Loop 검토 화면에서 사용하는 헬퍼.

중요: 여기서 반영하는 사용자의 판단은 아직 PostgreSQL에 저장되지 않는다.
지금은 현재 Streamlit 세션의 normalized_df만 갱신한다. human_reviews 테이블에
실제로 저장하는 기능은 Phase 6에서 추가한다.
"""

import polars as pl

REVIEW_ACTIONS = {
    "승인 (제안 기관으로 확정)": "APPROVE",
    "다른 금융기관으로 변경": "CHANGE_INSTITUTION",
    "금융기관 아님": "NOT_FINANCIAL_INSTITUTION",
    "판단 보류": "HOLD",
}


def apply_human_decision(
    df: pl.DataFrame,
    match_columns: dict[str, str],
    action: str,
    override_institution: tuple[int, str] | None = None,
) -> pl.DataFrame:
    """match_columns와 일치하는 모든 행의 검토 결과를 사용자의 판단으로 덮어쓴다."""
    if action not in REVIEW_ACTIONS.values():
        raise ValueError(f"알 수 없는 action입니다: {action}")

    condition = pl.lit(True)
    for col, value in match_columns.items():
        condition = condition & (pl.col(col) == value)

    if action == "APPROVE":
        new_review_status, new_institution, new_institution_id = "AUTO", pl.col("canonical_institution"), pl.col("institution_id")
    elif action == "CHANGE_INSTITUTION":
        if override_institution is None:
            raise ValueError("CHANGE_INSTITUTION에는 override_institution이 필요합니다.")
        institution_id, canonical_name = override_institution
        new_review_status, new_institution, new_institution_id = "AUTO", pl.lit(canonical_name), pl.lit(institution_id)
    elif action == "NOT_FINANCIAL_INSTITUTION":
        new_review_status, new_institution, new_institution_id = "NOT_FINANCIAL_INSTITUTION", pl.lit(None), pl.lit(None)
    else:  # HOLD
        new_review_status, new_institution, new_institution_id = "HOLD", pl.col("canonical_institution"), pl.col("institution_id")

    return df.with_columns(
        [
            pl.when(condition).then(pl.lit(new_review_status)).otherwise(pl.col("review_status")).alias("review_status"),
            pl.when(condition).then(new_institution).otherwise(pl.col("canonical_institution")).alias("canonical_institution"),
            pl.when(condition).then(new_institution_id).otherwise(pl.col("institution_id")).alias("institution_id"),
            pl.when(condition).then(pl.lit("HUMAN")).otherwise(pl.col("normalization_method")).alias("normalization_method"),
            pl.when(condition).then(pl.lit(True)).otherwise(pl.col("user_confirmed")).alias("user_confirmed"),
        ]
    )
