"""apply_normalization()에 context_column을 넘겼을 때의 end-to-end 동작 테스트.

실제 임베딩 모델을 사용하므로, 모델을 쓸 수 없는 환경에서는 건너뜀(skip) 처리된다.
"""

import polars as pl
import pytest

from src.database.models import InstitutionAlias, InstitutionMaster

try:
    from src.embedding_service import encode_texts

    encode_texts(["연결 확인용 텍스트"])
    _EMBEDDING_AVAILABLE = True
    _EMBEDDING_ERROR = None
except Exception as e:
    _EMBEDDING_AVAILABLE = False
    _EMBEDDING_ERROR = str(e)

pytestmark = pytest.mark.skipif(
    not _EMBEDDING_AVAILABLE,
    reason=f"Embedding 모델을 사용할 수 없어 건너뜁니다: {_EMBEDDING_ERROR}",
)

THRESHOLD = 90.0


def _institutions():
    nh = InstitutionMaster(
        institution_id=1,
        canonical_name="NH농협은행",
        active=True,
        keywords="대출,차입,이자,예금,계좌,송금",
        negative_keywords="농산물,원재료,조합원,유통,증권",
    )
    nh.aliases = [InstitutionAlias(alias_text=t, alias_type="ALIAS", active=True) for t in ["농협은행", "농은", "NH농협"]]
    return [nh]


def test_apply_normalization_with_context_column_end_to_end():
    from src.normalization_pipeline import apply_normalization

    df = pl.DataFrame(
        {
            "거래처": ["농협", "농협"],
            "context_text": [
                "농협 | 운영자금 대출이자 지급 | 이자비용 | 장기차입금",
                "농협 | 농산물 구매대금 지급 | 원재료 | 외상매입금",
            ],
            "금액": [1000, 2000],
        }
    )

    result, error = apply_normalization(
        df, "거래처", _institutions(), THRESHOLD, use_embedding=True, context_column="context_text"
    )

    assert error is None
    rows = result.to_dicts()
    bank_row = next(r for r in rows if "대출이자" in r["context_text"])
    purchase_row = next(r for r in rows if "농산물" in r["context_text"])

    # "농협"은 rapidfuzz로도 "NH농협"과 유사도 90점이 나와 FAST PATH(Fuzzy)에서
    # 이미 자동 확정된다 — Context Rerank(AI PATH)까지 갈 필요가 없다.
    assert bank_row["review_status"] == "AUTO"
    assert bank_row["canonical_institution"] == "NH농협은행"
    assert bank_row["normalization_method"] == "FUZZY"

    # 같은 vendor("농협")가 Fuzzy로 자동 확정될 뻔했지만, 문맥에 혼동 방지
    # 키워드("농산물","원재료")가 있어 안전장치가 검토 필요로 되돌린다.
    assert purchase_row["review_status"] == "NEEDS_REVIEW"
    assert "안전장치" in purchase_row["reason"]
