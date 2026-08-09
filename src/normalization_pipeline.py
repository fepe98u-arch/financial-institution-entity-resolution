"""정규화 파이프라인: FAST PATH -> AI PATH(Embedding) -> Context Reranking.

300,000행을 Python으로 한 줄씩 반복하지 않는다. FAST PATH는 거래처 표현의
고유값만 매칭하고, AI PATH는 FAST PATH가 확정 못한(UNRESOLVED) 표현의
(거래처, context_text) 고유 조합만 임베딩한다. 두 결과 모두 Polars join으로
전체 행에 broadcast한다.

Context Reranking은 context_text 컬럼이 있을 때만 동작한다 (없으면 Phase 4와
동일하게 Embedding 결과를 항상 '검토 필요'로만 남긴다). context_text가 있으면
src/context_reranker.py의 규칙(혼동 방지 키워드 거부권 등)을 적용해서, 조건을
만족하는 경우에만 자동 확정한다.
"""

import polars as pl

from src.alias_matcher import build_lookup_table, match_exact_or_alias
from src.candidate_retriever import build_alias_embedding_index, find_embedding_candidates
from src.context_reranker import DEFAULT_EMBEDDING_FLOOR, evaluate_candidate, negative_keyword_hits
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
    "user_confirmed",
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
            "user_confirmed": False,
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
            "user_confirmed": False,
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
            "user_confirmed": False,
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
        "reason": f"Fuzzy 유사도 {top1.score:.1f}점 < threshold {fuzzy_auto_threshold:.1f}점 (AI PATH로 이어짐)",
        "user_confirmed": False,
    }


def resolve_vendor_expressions(unique_vendor_texts: list[str], institutions, fuzzy_auto_threshold: float) -> dict[str, dict]:
    """고유 거래처 표현 목록에 대해 FAST PATH 매칭을 1회씩 수행한다."""
    lookup = build_lookup_table(institutions)
    return {text: _resolve_one(text, lookup, fuzzy_auto_threshold) for text in unique_vendor_texts}


def _resolve_ai_path_one(
    vendor_text: str,
    context_text: str | None,
    candidates,
    institutions_by_id: dict,
    embedding_floor: float,
) -> dict:
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
            "user_confirmed": False,
        }

    top1 = candidates[0]
    top2 = candidates[1] if len(candidates) > 1 else None
    score_margin = (top1.score - top2.score) if top2 else None

    if context_text is not None:
        institution = institutions_by_id.get(top1.institution_id)
        if institution is None:
            method, confirmed = "CONTEXT_RERANK", False
            reason = "[Context Rerank] Master 정보를 찾을 수 없어 검토 필요"
        else:
            decision = evaluate_candidate(context_text, institution, top1.score, embedding_floor)
            method, confirmed = "CONTEXT_RERANK", decision.confirmed
            reason = f"[Context Rerank] {decision.reason}"
    else:
        method, confirmed = "EMBEDDING", False
        reason = (
            f"Embedding top1={top1.score:.3f}"
            + (f", top2={top2.score:.3f}" if top2 else "")
            + " — context_text가 없어 문맥 재평가를 하지 못함 (검토 필요)"
        )

    return {
        "normalized_expression": top1.matched_text,
        "canonical_institution": top1.canonical_name,
        "institution_id": top1.institution_id,
        "normalization_method": method,
        "top1_score": top1.score,
        "top2_candidate": top2.canonical_name if top2 else None,
        "top2_score": top2.score if top2 else None,
        "score_margin": score_margin,
        "review_status": "AUTO" if confirmed else "NEEDS_REVIEW",
        "reason": reason,
        "user_confirmed": False,
    }


def resolve_ai_path(
    pairs: list[tuple[str, str | None]], institutions, embedding_floor: float = DEFAULT_EMBEDDING_FLOOR
) -> dict[tuple[str, str | None], dict]:
    """(거래처, context_text) 고유 조합에 대해 Embedding(+가능하면 Context Rerank)을 1회씩 수행한다."""
    texts, owners, embeddings = build_alias_embedding_index(institutions)
    if embeddings is None:
        return {}

    unique_vendor_texts = list(dict.fromkeys(p[0] for p in pairs))
    candidates_by_text = find_embedding_candidates(unique_vendor_texts, texts, owners, embeddings, limit=2)
    institutions_by_id = {i.institution_id: i for i in institutions}

    return {
        (vendor_text, context_text): _resolve_ai_path_one(
            vendor_text, context_text, candidates_by_text.get(vendor_text, []), institutions_by_id, embedding_floor
        )
        for vendor_text, context_text in pairs
    }


def _apply_fuzzy_negative_keyword_veto(
    result: pl.DataFrame, vendor_column: str, context_column: str, institutions
) -> pl.DataFrame:
    """Fuzzy로 자동 확정된 결과라도, 문맥에 혼동 방지 키워드가 있으면 검토 필요로 되돌린다.

    FAST PATH의 Fuzzy 단계는 문맥을 보지 않는다. 그런데 "농협"처럼 짧은 표현은
    "NH농협" 별칭과 rapidfuzz 유사도가 90점(threshold)까지 나올 수 있어, 문맥이
    "농산물 구매"인 경우에도 자동 확정될 위험이 있다. 이 안전장치가 그것을 막는다.
    EXACT/ALIAS(완전히 같은 표현으로 확정)에는 적용하지 않는다 — 그 정도로
    명확한 표현이 혼동 방지 키워드가 있는 문맥에서 나올 가능성은 낮고, 명백한
    표현은 빠르게 확정한다는 FAST PATH 원칙을 지키기 위함이다.
    """
    fuzzy_auto = (pl.col("normalization_method") == "FUZZY") & (pl.col("review_status") == "AUTO")
    candidates_df = result.filter(fuzzy_auto).select([vendor_column, context_column, "institution_id"]).unique()
    if candidates_df.height == 0:
        return result

    institutions_by_id = {i.institution_id: i for i in institutions}
    veto_rows = []
    for vendor_text, context_text, institution_id in candidates_df.iter_rows():
        institution = institutions_by_id.get(institution_id)
        if institution is None:
            continue
        hits = negative_keyword_hits(context_text, institution)
        if hits:
            veto_rows.append(
                {
                    vendor_column: vendor_text,
                    context_column: context_text,
                    "review_status__veto": "NEEDS_REVIEW",
                    "reason__veto": (
                        f"[안전장치] Fuzzy로 '{institution.canonical_name}' 자동 확정됐으나 "
                        f"문맥에 혼동 방지 키워드 {hits} 포함 → 검토 필요로 전환"
                    ),
                }
            )

    if not veto_rows:
        return result

    veto_df = pl.DataFrame(veto_rows)
    result = result.join(veto_df, on=[vendor_column, context_column], how="left")
    result = result.with_columns(
        [
            pl.when(pl.col("review_status__veto").is_not_null())
            .then(pl.col("review_status__veto"))
            .otherwise(pl.col("review_status"))
            .alias("review_status"),
            pl.when(pl.col("review_status__veto").is_not_null())
            .then(pl.col("reason__veto"))
            .otherwise(pl.col("reason"))
            .alias("reason"),
        ]
    )
    return result.drop(["review_status__veto", "reason__veto"])


def apply_normalization(
    df: pl.DataFrame,
    vendor_column: str,
    institutions,
    fuzzy_auto_threshold: float,
    use_embedding: bool = True,
    context_column: str | None = None,
    embedding_floor: float = DEFAULT_EMBEDDING_FLOOR,
) -> tuple[pl.DataFrame, str | None]:
    """df에 정규화 결과 컬럼을 추가한 새 DataFrame을 반환한다 (원본 컬럼 유지).

    Returns: (결과 DataFrame, Embedding/Context Rerank 단계 에러 메시지 또는 None)
    """
    unique_texts = [t for t in df.select(pl.col(vendor_column).unique()).to_series().to_list() if t is not None]
    resolved = resolve_vendor_expressions(unique_texts, institutions, fuzzy_auto_threshold)

    fast_mapping_df = pl.DataFrame(
        {
            vendor_column: unique_texts,
            **{field: [resolved[t][field] for t in unique_texts] for field in RESULT_FIELDS},
        }
    )
    result = df.join(fast_mapping_df, on=vendor_column, how="left")
    result = result.with_columns(pl.col(vendor_column).alias("detected_expression"))

    has_context = context_column is not None and context_column in result.columns
    pair_cols = [vendor_column, context_column] if has_context else [vendor_column]

    if has_context:
        result = _apply_fuzzy_negative_keyword_veto(result, vendor_column, context_column, institutions)

    if not use_embedding:
        return result, None

    unresolved_pairs_df = result.filter(pl.col("normalization_method") == "UNRESOLVED").select(pair_cols).unique()
    if unresolved_pairs_df.height == 0:
        return result, None

    if has_context:
        pairs = list(unresolved_pairs_df.iter_rows())
    else:
        pairs = [(row[0], None) for row in unresolved_pairs_df.iter_rows()]

    try:
        ai_results = resolve_ai_path(pairs, institutions, embedding_floor)
    except Exception as e:  # 모델 다운로드 실패, 인터넷 없음 등
        return result, f"Embedding 모델을 사용할 수 없어 FAST PATH 결과만 사용합니다: {e}"

    if not ai_results:
        return result, None

    ai_rows = []
    for (vendor_text, context_text), fields in ai_results.items():
        row = {vendor_column: vendor_text}
        if has_context:
            row[context_column] = context_text
        row.update(fields)
        ai_rows.append(row)

    ai_df = pl.DataFrame(ai_rows).rename({field: f"{field}__ai" for field in RESULT_FIELDS})
    result = result.join(ai_df, on=pair_cols, how="left")

    is_unresolved = pl.col("normalization_method") == "UNRESOLVED"
    result = result.with_columns(
        [
            pl.when(is_unresolved & pl.col(f"{field}__ai").is_not_null())
            .then(pl.col(f"{field}__ai"))
            .otherwise(pl.col(field))
            .alias(field)
            for field in RESULT_FIELDS
        ]
    )
    result = result.drop([f"{field}__ai" for field in RESULT_FIELDS])
    return result, None


def build_persistable_rows(
    result_df: pl.DataFrame,
    institutions_by_id: dict,
    voucher_column: str | None = None,
    context_column: str | None = None,
) -> list[dict]:
    """normalization_results 테이블(Phase 6)에 저장할 행(dict) 목록을 만든다.

    voucher_column이 매핑되어 있으면 그 값을 original_row_id로 쓰고, 없으면
    행 순서 번호를 문자열로 쓴다. institution_type은 institutions_by_id로
    조회한다 (파이프라인 결과 자체에는 institution_type이 없기 때문).
    """
    rows = []
    for i, row in enumerate(result_df.to_dicts()):
        institution_id = row.get("institution_id")
        institution = institutions_by_id.get(institution_id) if institution_id is not None else None
        original_row_id = row.get(voucher_column) if voucher_column else None
        rows.append(
            {
                "original_row_id": str(original_row_id) if original_row_id is not None else str(i),
                "detected_expression": row.get("detected_expression"),
                "normalized_expression": row.get("normalized_expression"),
                "canonical_institution": row.get("canonical_institution"),
                "institution_id": institution_id,
                "institution_type": institution.institution_type if institution else None,
                "normalization_method": row.get("normalization_method"),
                "top1_score": row.get("top1_score"),
                "top2_candidate": row.get("top2_candidate"),
                "top2_score": row.get("top2_score"),
                "score_margin": row.get("score_margin"),
                "review_status": row.get("review_status"),
                "context_text": row.get(context_column) if context_column else None,
                "reason": row.get("reason"),
                "user_confirmed": bool(row.get("user_confirmed", False)),
            }
        )
    return rows
