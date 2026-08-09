"""회사 제출 금융기관 목록과 분개장에서 발견된 금융기관을 비교한다 (완전성 검토).

A = 회사 제출 목록에서 표준 금융기관으로 확인된 것
B = 분개장에서 표준 금융기관으로 확인된 것

둘 다 review_status가 AUTO/HUMAN인 것만 "확인됨"으로 센다 — 아직 검토 중인
후보(NEEDS_REVIEW)까지 완전성 비교에 넣으면, 잘못된 후보 때문에 비교 결과가
흔들릴 수 있기 때문이다.

가장 중요한 결과는 B - A: 회사 제출 목록에는 없지만 분개장에서 발견된
금융기관이다. 이걸 '누락 확정'이라고 부르지 않는다 — '추가 검토 후보'라고
표현한다. 최종 판단은 감사인이 한다 (이 프로그램은 확정하지 않는다).
"""

import polars as pl

from src.normalization_pipeline import apply_normalization

CONFIRMED_STATUSES = ["AUTO", "HUMAN"]


def normalize_company_list(
    df: pl.DataFrame,
    institution_column: str,
    institutions,
    fuzzy_auto_threshold: float,
    embedding_floor: float,
    use_embedding: bool = True,
) -> tuple[pl.DataFrame, str | None]:
    """회사 제출 목록의 기관명을 표준 금융기관으로 정규화한다.

    분개장 정규화와 동일한 파이프라인(FAST PATH -> AI PATH)을 그대로 재사용한다.
    회사 제출 목록에는 적요/계정과목 같은 문맥이 없으므로 context_column은 쓰지 않는다.
    """
    return apply_normalization(
        df,
        institution_column,
        institutions,
        fuzzy_auto_threshold,
        use_embedding=use_embedding,
        context_column=None,
        embedding_floor=embedding_floor,
    )


def _confirmed_institution_names(result_df: pl.DataFrame) -> set[str]:
    confirmed = result_df.filter(pl.col("review_status").is_in(CONFIRMED_STATUSES))
    return set(confirmed["canonical_institution"].drop_nulls().unique().to_list())


def compare_completeness(
    company_result_df: pl.DataFrame, journal_result_df: pl.DataFrame, company_institution_column: str
) -> dict:
    """A(회사 제출)와 B(분개장 발견)를 비교해서 세 그룹과 미확인 목록을 반환한다."""
    company_set = _confirmed_institution_names(company_result_df)
    journal_set = _confirmed_institution_names(journal_result_df)

    unidentified_in_company_list = (
        company_result_df.filter(~pl.col("review_status").is_in(CONFIRMED_STATUSES))
        .select(company_institution_column)
        .unique()
        .to_series()
        .to_list()
    )

    return {
        "both": sorted(company_set & journal_set),  # A ∩ B
        "additional_candidates": sorted(journal_set - company_set),  # B - A (가장 중요)
        "company_only": sorted(company_set - journal_set),  # A - B
        "unidentified_in_company_list": sorted(unidentified_in_company_list),
    }


def summarize_journal_by_institution(
    journal_result_df: pl.DataFrame, canonical_names: list[str], amount_column: str | None = None
) -> pl.DataFrame:
    """확정된(AUTO/HUMAN) 분개 중, 지정한 기관들에 대한 건수/금액을 집계한다."""
    if not canonical_names:
        return pl.DataFrame({"canonical_institution": [], "journal_count": []})

    confirmed = journal_result_df.filter(
        pl.col("review_status").is_in(CONFIRMED_STATUSES) & pl.col("canonical_institution").is_in(canonical_names)
    )

    agg_exprs = [pl.len().alias("journal_count")]
    if amount_column and amount_column in journal_result_df.columns:
        agg_exprs.append(pl.col(amount_column).sum().alias("total_amount"))

    return confirmed.group_by("canonical_institution").agg(agg_exprs)


def get_institution_detail_rows(
    journal_result_df: pl.DataFrame, canonical_institution: str, detail_columns: list[str]
) -> pl.DataFrame:
    """추가 검토 후보 하나에 대해, 분개장에서 발견된 관련 원본 분개 행을 모은다."""
    confirmed = journal_result_df.filter(
        pl.col("review_status").is_in(CONFIRMED_STATUSES) & (pl.col("canonical_institution") == canonical_institution)
    )
    available_columns = [c for c in detail_columns if c in confirmed.columns]
    return confirmed.select(available_columns) if available_columns else confirmed
