"""FAST PATH/AI PATH/Context Rerank가 실제로 얼마나 도움이 되는지 측정한다.

완전히 가상의 라벨링된 평가 데이터셋(EVALUATION_DATASET)에 대해 4가지 구성을
각각 돌려서 실제 지표를 계산한다. 실제 데이터로 검증한 적 없는 임의의 점수는
절대 만들지 않는다 — 여기 나오는 모든 수치는 이 가상 데이터셋에 대한 실제
계산값이며, 공식 성능 지표나 감사 기준이 아니다.

Baseline1_Exact_Alias: Exact + Alias Match만 (Fuzzy/Embedding/Context 없음)
Baseline2_Fuzzy:       + Fuzzy Match
Model3_Embedding:      + Embedding (문맥 없음)
Model4_ContextRerank:  + Context Reranking (전체 파이프라인)
"""

import polars as pl

from src.normalization_pipeline import apply_normalization

# (거래처, context_text, true_label). true_label이 None이면 "이 금융기관
# Master의 어떤 기관과도 매칭되면 안 됨"이라는 뜻이다.
EVALUATION_DATASET: list[tuple[str, str, str | None]] = [
    # --- NH농협은행: 명확한 표현 ---
    ("NH농협은행", "NH농협은행 | 대출이자 지급 | 이자비용 | 장기차입금", "NH농협은행"),
    ("농협은행", "농협은행 | 정기예금 예치 | 정기예금 | 보통예금", "NH농협은행"),
    ("NH농협", "NH농협 | 계좌이체 수수료 | 수수료비용 | 보통예금", "NH농협은행"),
    ("농은", "농은 | 대출이자 지급 | 이자비용 | 장기차입금", "NH농협은행"),
    ("Nonghyup Bank", "Nonghyup Bank | 외화 송금 | 외화예금 | 보통예금", "NH농협은행"),
    ("NH Bank", "NH Bank | 외화 송금 수수료 | 수수료비용 | 보통예금", "NH농협은행"),
    # --- NH농협은행: 오타/지점명 (Fuzzy로만 잡을 수 있음) ---
    ("농협은행 부산지점", "농협은행 부산지점 | 대출이자 지급 | 이자비용 | 장기차입금", "NH농협은행"),
    ("(주)농협은행", "(주)농협은행 | 보통예금 입금 | 보통예금 | 제품매출", "NH농협은행"),
    # --- NH농협은행: 문맥이 있어야만 확정 가능한 모호한 표현 ---
    ("농협", "농협 | 운영자금 대출이자 지급 | 이자비용 | 장기차입금", "NH농협은행"),
    ("농협", "농협 | 정기예금 이자 수령 | 이자수익 | 정기예금", "NH농협은행"),
    # --- 같은 "농협"이지만 문맥이 구매처를 가리키는 경우: 자동 확정하면 안 됨.
    # Baseline2(Fuzzy)는 문맥을 안 보기 때문에 이 표현도 그냥 NH농협은행으로
    # 자동 확정해버린다 — Context Rerank(Model4)가 왜 필요한지 보여주는 사례다.
    ("농협", "농협 | 농산물 구매대금 지급 | 원재료 | 외상매입금", None),
    # --- KB국민은행 ---
    ("KB국민은행", "KB국민은행 | 보통예금 입금 | 보통예금 | 제품매출", "KB국민은행"),
    ("국민은행", "국민은행 | 대출이자 지급 | 이자비용 | 장기차입금", "KB국민은행"),
    ("KB국민", "KB국민 | 계좌이체 수수료 | 수수료비용 | 보통예금", "KB국민은행"),
    ("KB BANK", "KB BANK | 외화송금 | 외화예금 | 보통예금", "KB국민은행"),
    ("케이비국민", "케이비국민 | 외화송금 수수료 | 수수료비용 | 보통예금", "KB국민은행"),
    # --- 신한은행 ---
    ("신한은행", "신한은행 | 보통예금 이자 수령 | 이자수익 | 보통예금", "신한은행"),
    ("신한", "신한 | 대출이자 지급 | 이자비용 | 장기차입금", "신한은행"),
    ("신한 BIZ", "신한 BIZ | 은행수수료 지급 | 수수료비용 | 보통예금", "신한은행"),
    # --- Negative: 이름은 비슷하지만 자동 확정하면 안 되는 사례 ---
    ("OO농협", "OO농협 | 농산물 구매대금 지급 | 원재료 | 외상매입금", None),
    ("농협유통", "농협유통 | 상품 매입대금 지급 | 상품 | 외상매입금", None),
    ("NH투자", "NH투자 | 증권 매매 정산 | 단기매매증권 | 보통예금", None),
    # --- Negative: 완전히 무관한 일반 거래처 ---
    ("테스트전자", "테스트전자 | 제품 판매대금 수령 | 제품매출 | 보통예금", None),
    ("샘플물류", "샘플물류 | 운송비 지급 | 운반비 | 외상매입금", None),
    ("가상상사", "가상상사 | 용역비 지급 | 용역비 | 외상매입금", None),
    ("ABC부품", "ABC부품 | 부품 구매대금 지급 | 원재료 | 외상매입금", None),
]

# rapidfuzz 최고점이 100이므로, 101을 threshold로 주면 Fuzzy로는 절대 자동 확정되지 않는다
# (기존 normalization_pipeline.py를 건드리지 않고 "Fuzzy 없음" 상태를 만드는 방법).
_FUZZY_DISABLED_THRESHOLD = 101.0

VARIANTS = {
    "Baseline1_Exact_Alias": {"use_fuzzy": False, "use_embedding": False, "use_context": False},
    "Baseline2_Fuzzy": {"use_fuzzy": True, "use_embedding": False, "use_context": False},
    "Model3_Embedding": {"use_fuzzy": True, "use_embedding": True, "use_context": False},
    "Model4_ContextRerank": {"use_fuzzy": True, "use_embedding": True, "use_context": True},
}


def build_evaluation_dataframe() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "vendor": [row[0] for row in EVALUATION_DATASET],
            "context_text": [row[1] for row in EVALUATION_DATASET],
            "true_label": [row[2] for row in EVALUATION_DATASET],
        }
    )


def run_variant(
    variant_name: str, institutions, fuzzy_auto_threshold: float, embedding_floor: float
) -> tuple[pl.DataFrame, str | None]:
    """평가 데이터셋에 지정한 구성(variant)으로 정규화를 실행한다.

    Returns: (true_label이 포함된 결과 DataFrame, 에러 메시지 또는 None)
    """
    if variant_name not in VARIANTS:
        raise ValueError(f"알 수 없는 variant입니다: {variant_name}")
    config = VARIANTS[variant_name]
    df = build_evaluation_dataframe()
    effective_threshold = fuzzy_auto_threshold if config["use_fuzzy"] else _FUZZY_DISABLED_THRESHOLD

    return apply_normalization(
        df,
        "vendor",
        institutions,
        effective_threshold,
        use_embedding=config["use_embedding"],
        context_column="context_text" if config["use_context"] else None,
        embedding_floor=embedding_floor,
    )


def compute_metrics(result_df: pl.DataFrame) -> dict:
    """실제 예측 결과와 true_label을 비교해서 지표를 계산한다 (임의 수치 없음)."""
    true_positive = false_negative = false_positive = true_negative = 0

    for row in result_df.to_dicts():
        true_label = row.get("true_label")
        predicted_label = (
            row.get("canonical_institution") if row.get("review_status") in ("AUTO", "HUMAN") else None
        )

        if true_label is not None:
            if predicted_label == true_label:
                true_positive += 1
            elif predicted_label is None:
                false_negative += 1
            else:
                false_positive += 1  # 다른 기관으로 잘못 자동 확정 (위험)
        else:
            if predicted_label is None:
                true_negative += 1
            else:
                false_positive += 1  # 매칭되면 안 되는데 자동 확정해버림 (가장 위험)

    total = true_positive + false_negative + false_positive + true_negative
    positive_total = true_positive + false_negative
    predicted_total = true_positive + false_positive

    accuracy = (true_positive + true_negative) / total if total else None
    precision = true_positive / predicted_total if predicted_total else None
    recall = true_positive / positive_total if positive_total else None
    f1 = (2 * precision * recall / (precision + recall)) if precision and recall else None
    coverage = predicted_total / total if total else None
    false_normalization_rate = false_positive / predicted_total if predicted_total else 0.0

    return {
        "total": total,
        "true_positive": true_positive,
        "false_negative": false_negative,
        "false_positive": false_positive,
        "true_negative": true_negative,
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "coverage": coverage,
        "manual_review_rate": (1 - coverage) if coverage is not None else None,
        "false_normalization_rate": false_normalization_rate,
    }


def run_all_variants(institutions, fuzzy_auto_threshold: float, embedding_floor: float) -> dict[str, dict]:
    """4가지 구성을 모두 돌려서 variant 이름별 지표를 반환한다."""
    results = {}
    for variant_name in VARIANTS:
        result_df, error = run_variant(variant_name, institutions, fuzzy_auto_threshold, embedding_floor)
        metrics = compute_metrics(result_df)
        metrics["embedding_error"] = error
        results[variant_name] = metrics
    return results
