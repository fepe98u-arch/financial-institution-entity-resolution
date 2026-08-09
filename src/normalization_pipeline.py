"""FAST PATH 정규화 파이프라인: Exact -> Alias -> Fuzzy 순서로 시도한다.

300,000행을 Python으로 한 줄씩 반복하지 않는다. 대신 (1) 거래처 표현의
고유값만 추려서 매칭하고 (2) Polars join으로 전체 행에 결과를 broadcast한다.
같은 표현이 수만 번 반복돼도 매칭은 한 번만 수행된다.

AI PATH(Embedding, Context Reranking)는 아직 없으므로, 여기서 확정하지 못한
표현은 전부 UNRESOLVED로 남는다 (Phase 4~5에서 이어짐).
"""

import polars as pl

from src.alias_matcher import build_lookup_table, match_exact_or_alias
from src.fuzzy_matcher import find_fuzzy_candidates

RESULT_FIELDS = [
    "normalized_expression",
    "canonical_institution",
    "institution_id",
    "normalization_method",
    "top1_score",
    "top2_candidate",
    "top2_score",
    "score_margin",
    "review_status",
    "reason",
]


def _resolve_one(vendor_text: str, lookup, fuzzy_auto_threshold: float) -> dict:
    exact = match_exact_or_alias(vendor_text, lookup)
    if exact is not None:
        method = "EXACT" if exact.match_source == "CANONICAL" else "ALIAS"
        reason = "Master 정확 일치" if method == "EXACT" else f"Alias Master 정확 일치 ({exact.match_text})"
        return {
            "normalized_expression": exact.match_text,
            "canonical_institution": exact.canonical_name,
            "institution_id": exact.institution_id,
            "normalization_method": method,
            "top1_score": 100.0,
            "top2_candidate": None,
            "top2_score": None,
            "score_margin": None,
            "review_status": "AUTO",
            "reason": reason,
        }

    candidates = find_fuzzy_candidates(vendor_text, lookup, limit=2)
    if not candidates:
        return {
            "normalized_expression": None,
            "canonical_institution": None,
            "institution_id": None,
            "normalization_method": "UNRESOLVED",
            "top1_score": None,
            "top2_candidate": None,
            "top2_score": None,
            "score_margin": None,
            "review_status": "NEEDS_REVIEW",
            "reason": "등록된 금융기관 Master/Alias가 없어 비교할 후보가 없음",
        }

    top1 = candidates[0]
    top2 = candidates[1] if len(candidates) > 1 else None
    score_margin = (top1.score - top2.score) if top2 else None

    if top1.score >= fuzzy_auto_threshold:
        return {
            "normalized_expression": top1.matched_text,
            "canonical_institution": top1.canonical_name,
            "institution_id": top1.institution_id,
            "normalization_method": "FUZZY",
            "top1_score": top1.score,
            "top2_candidate": top2.canonical_name if top2 else None,
            "top2_score": top2.score if top2 else None,
            "score_margin": score_margin,
            "review_status": "AUTO",
            "reason": f"Fuzzy 유사도 {top1.score:.1f}점 >= threshold {fuzzy_auto_threshold:.1f}점",
        }

    return {
        "normalized_expression": None,
        "canonical_institution": None,
        "institution_id": None,
        "normalization_method": "UNRESOLVED",
        "top1_score": top1.score,
        "top2_candidate": top2.canonical_name if top2 else None,
        "top2_score": top2.score if top2 else None,
        "score_margin": score_margin,
        "review_status": "NEEDS_REVIEW",
        "reason": (
            f"Fuzzy 유사도 {top1.score:.1f}점 < threshold {fuzzy_auto_threshold:.1f}점 "
            "(AI PATH/Human Review는 Phase 4~6에서 구현)"
        ),
    }


def resolve_vendor_expressions(unique_vendor_texts: list[str], institutions, fuzzy_auto_threshold: float) -> dict[str, dict]:
    """고유 거래처 표현 목록에 대해 FAST PATH 매칭을 1회씩 수행한다."""
    lookup = build_lookup_table(institutions)
    return {text: _resolve_one(text, lookup, fuzzy_auto_threshold) for text in unique_vendor_texts}


def apply_normalization(df: pl.DataFrame, vendor_column: str, institutions, fuzzy_auto_threshold: float) -> pl.DataFrame:
    """df에 정규화 결과 컬럼을 추가한 새 DataFrame을 반환한다 (원본 컬럼 유지)."""
    unique_texts = [t for t in df.select(pl.col(vendor_column).unique()).to_series().to_list() if t is not None]
    resolved = resolve_vendor_expressions(unique_texts, institutions, fuzzy_auto_threshold)

    mapping_df = pl.DataFrame(
        {
            vendor_column: unique_texts,
            **{field: [resolved[t][field] for t in unique_texts] for field in RESULT_FIELDS},
        }
    )

    result = df.join(mapping_df, on=vendor_column, how="left")
    return result.with_columns(pl.col(vendor_column).alias("detected_expression"))
