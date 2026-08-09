"""정규화 파이프라인: FAST PATH(Exact -> Alias -> Fuzzy) 다음에 AI PATH(Embedding)를 시도한다.

300,000행을 Python으로 한 줄씩 반복하지 않는다. 대신 (1) 거래처 표현의
고유값만 추려서 매칭하고 (2) Polars join으로 전체 행에 결과를 broadcast한다.
같은 표현이 수만 번 반복돼도 매칭/임베딩은 한 번만 수행된다.

AI PATH는 FAST PATH로 확정하지 못한(UNRESOLVED) 표현에만 실행한다. 문맥
재평가(Context Reranking, Phase 5)가 아직 없기 때문에, Embedding 결과는
점수가 높아도 자동으로 확정하지 않고 항상 '검토 필요'로만 표시한다 —
candidate_retriever.py에 적어둔 실측 결과("OO농협"이 "NH농협은행"과 0.8점대
유사도로 계산됨)를 보면, 문맥 없이 자동 확정하는 것은 위험하다.
"""

import polars as pl

from src.alias_matcher import build_lookup_table, match_exact_or_alias
from src.candidate_retriever import build_alias_embedding_index, find_embedding_candidates
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


def apply_embedding_path(resolved: dict[str, dict], institutions) -> tuple[dict[str, dict], str | None]:
    """FAST PATH에서 UNRESOLVED로 남은 표현만 Embedding으로 재시도한다.

    Returns:
        (갱신된 resolved 딕셔너리, 에러 메시지 또는 None). 모델을 불러오지
        못하면(예: 인터넷 없음) 예외를 던지지 않고 에러 메시지를 반환해서
        FAST PATH 결과만으로도 앱이 계속 동작하게 한다.
    """
    unresolved_texts = [text for text, r in resolved.items() if r["normalization_method"] == "UNRESOLVED"]
    if not unresolved_texts:
        return resolved, None

    try:
        texts, owners, embeddings = build_alias_embedding_index(institutions)
        if embeddings is None:
            return resolved, None
        candidates_by_text = find_embedding_candidates(unresolved_texts, texts, owners, embeddings, limit=2)
    except Exception as e:  # 모델 다운로드 실패, 인터넷 없음 등
        return resolved, f"Embedding 모델을 사용할 수 없어 FAST PATH 결과만 사용합니다: {e}"

    updated = dict(resolved)
    for vendor_text in unresolved_texts:
        candidates = candidates_by_text.get(vendor_text, [])
        if not candidates:
            continue
        top1 = candidates[0]
        top2 = candidates[1] if len(candidates) > 1 else None
        fast_path_reason = resolved[vendor_text]["reason"]
        updated[vendor_text] = {
            "normalized_expression": top1.matched_text,
            "canonical_institution": top1.canonical_name,
            "institution_id": top1.institution_id,
            "normalization_method": "EMBEDDING",
            "top1_score": top1.score,
            "top2_candidate": top2.canonical_name if top2 else None,
            "top2_score": top2.score if top2 else None,
            "score_margin": (top1.score - top2.score) if top2 else None,
            "review_status": "NEEDS_REVIEW",
            "reason": (
                f"[FAST PATH] {fast_path_reason} / "
                f"[Embedding] top1={top1.score:.3f}"
                + (f", top2={top2.score:.3f}" if top2 else "")
                + " — 문맥 재평가(Context Reranking, Phase 5)가 없어 자동 확정하지 않고 검토 대상으로만 표시함."
            ),
        }
    return updated, None


def apply_normalization(
    df: pl.DataFrame,
    vendor_column: str,
    institutions,
    fuzzy_auto_threshold: float,
    use_embedding: bool = True,
) -> tuple[pl.DataFrame, str | None]:
    """df에 정규화 결과 컬럼을 추가한 새 DataFrame을 반환한다 (원본 컬럼 유지).

    Returns: (결과 DataFrame, Embedding 단계 에러 메시지 또는 None)
    """
    unique_texts = [t for t in df.select(pl.col(vendor_column).unique()).to_series().to_list() if t is not None]
    resolved = resolve_vendor_expressions(unique_texts, institutions, fuzzy_auto_threshold)

    embedding_error = None
    if use_embedding:
        resolved, embedding_error = apply_embedding_path(resolved, institutions)

    mapping_df = pl.DataFrame(
        {
            vendor_column: unique_texts,
            **{field: [resolved[t][field] for t in unique_texts] for field in RESULT_FIELDS},
        }
    )

    result = df.join(mapping_df, on=vendor_column, how="left")
    result = result.with_columns(pl.col(vendor_column).alias("detected_expression"))
    return result, embedding_error
