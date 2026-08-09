import polars as pl
import pytest

from src.database.models import InstitutionAlias, InstitutionMaster
from src.evaluation import compute_metrics, run_all_variants, run_variant

try:
    from src.embedding_service import encode_texts

    encode_texts(["연결 확인용 텍스트"])
    _EMBEDDING_AVAILABLE = True
    _EMBEDDING_ERROR = None
except Exception as e:
    _EMBEDDING_AVAILABLE = False
    _EMBEDDING_ERROR = str(e)


def _institutions():
    nh = InstitutionMaster(
        institution_id=1,
        canonical_name="NH농협은행",
        institution_type="BANK",
        active=True,
        keywords="대출,차입,이자,예금,계좌,송금",
        negative_keywords="농산물,원재료,조합원,유통,증권",
    )
    nh.aliases = [
        InstitutionAlias(alias_text=t, alias_type="ALIAS", active=True)
        for t in ["농협은행", "NH농협", "농은", "Nonghyup Bank", "NH Bank"]
    ]
    kb = InstitutionMaster(institution_id=2, canonical_name="KB국민은행", institution_type="BANK", active=True)
    kb.aliases = [
        InstitutionAlias(alias_text=t, alias_type="ALIAS", active=True)
        for t in ["국민은행", "KB국민", "KB BANK", "케이비국민"]
    ]
    shinhan = InstitutionMaster(institution_id=3, canonical_name="신한은행", institution_type="BANK", active=True)
    shinhan.aliases = [InstitutionAlias(alias_text=t, alias_type="ALIAS", active=True) for t in ["신한", "신한 BIZ"]]
    return [nh, kb, shinhan]


def test_compute_metrics_perfect_prediction():
    df = pl.DataFrame(
        {
            "true_label": ["NH농협은행", None],
            "canonical_institution": ["NH농협은행", None],
            "review_status": ["AUTO", "UNRESOLVED"],
        }
    )
    metrics = compute_metrics(df)
    assert metrics["true_positive"] == 1
    assert metrics["true_negative"] == 1
    assert metrics["accuracy"] == 1.0
    assert metrics["false_normalization_rate"] == 0.0


def test_compute_metrics_counts_false_positive_for_wrongly_confirmed_negative():
    """true_label이 None인데 AUTO로 확정되면 false_positive다 (가장 위험한 경우)."""
    df = pl.DataFrame(
        {
            "true_label": [None],
            "canonical_institution": ["NH농협은행"],
            "review_status": ["AUTO"],
        }
    )
    metrics = compute_metrics(df)
    assert metrics["false_positive"] == 1
    assert metrics["false_normalization_rate"] == 1.0


def test_compute_metrics_needs_review_counts_as_false_negative_not_wrong():
    df = pl.DataFrame(
        {
            "true_label": ["NH농협은행"],
            "canonical_institution": [None],
            "review_status": ["NEEDS_REVIEW"],
        }
    )
    metrics = compute_metrics(df)
    assert metrics["false_negative"] == 1
    assert metrics["false_positive"] == 0
    assert metrics["coverage"] == 0.0


def test_baseline1_exact_alias_only_misses_fuzzy_and_context_cases():
    """Baseline1(Exact+Alias만)은 오타/지점명/모호한 표현을 전혀 못 잡는다."""
    result_df, error = run_variant("Baseline1_Exact_Alias", _institutions(), fuzzy_auto_threshold=90.0, embedding_floor=0.85)
    assert error is None
    metrics = compute_metrics(result_df)
    # "농협은행 부산지점"처럼 Fuzzy가 필요한 사례는 Exact/Alias로 못 잡으므로 recall이 낮아야 한다.
    assert metrics["recall"] < 1.0
    assert metrics["false_positive"] == 0  # 명확한 것만 다루므로 잘못 확정하는 일은 없어야 한다


def test_baseline2_fuzzy_without_context_wrongly_confirms_ambiguous_purchase_case():
    """실측 확인: Baseline2(Fuzzy만, 문맥 없음)는 '농협'+농산물 구매 문맥도 그냥 NH농협은행으로 확정해버린다.

    이게 바로 Context Rerank(Model4)가 필요한 이유를 보여주는 실제 사례다.
    """
    result_df, error = run_variant("Baseline2_Fuzzy", _institutions(), fuzzy_auto_threshold=90.0, embedding_floor=0.85)
    assert error is None

    ambiguous_row = result_df.filter(pl.col("context_text").str.contains("농산물")).to_dicts()[0]
    assert ambiguous_row["review_status"] == "AUTO"
    assert ambiguous_row["canonical_institution"] == "NH농협은행"  # 실제로는 true_label=None이어야 함

    metrics = compute_metrics(result_df)
    assert metrics["false_positive"] >= 1


@pytest.mark.skipif(not _EMBEDDING_AVAILABLE, reason=f"Embedding 모델을 사용할 수 없어 건너뜁니다: {_EMBEDDING_ERROR}")
def test_model4_context_rerank_avoids_the_false_positive_baseline2_makes():
    """Model4(Context Rerank 포함)는 baseline2가 틀리는 그 사례를 검토 필요로 되돌린다."""
    result_df, error = run_variant("Model4_ContextRerank", _institutions(), fuzzy_auto_threshold=90.0, embedding_floor=0.85)
    assert error is None

    ambiguous_row = result_df.filter(pl.col("context_text").str.contains("농산물")).to_dicts()[0]
    assert ambiguous_row["review_status"] == "NEEDS_REVIEW"

    metrics = compute_metrics(result_df)
    assert metrics["false_positive"] == 0  # Context Rerank 덕분에 잘못된 자동 확정이 없어야 한다


@pytest.mark.skipif(not _EMBEDDING_AVAILABLE, reason=f"Embedding 모델을 사용할 수 없어 건너뜁니다: {_EMBEDDING_ERROR}")
def test_run_all_variants_returns_metrics_for_every_variant():
    results = run_all_variants(_institutions(), fuzzy_auto_threshold=90.0, embedding_floor=0.85)
    assert set(results.keys()) == {
        "Baseline1_Exact_Alias",
        "Baseline2_Fuzzy",
        "Model3_Embedding",
        "Model4_ContextRerank",
    }
    for metrics in results.values():
        assert metrics["total"] == 26  # 평가 데이터셋 전체 행 수
