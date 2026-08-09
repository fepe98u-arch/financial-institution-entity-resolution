"""동일한 표현을 반복해서 재계산하지 않는지 직접 증명하는 테스트.

계획서 42번 섹션 17번: "동일한 명확 표현 Cache 재사용". apply_normalization은
내부적으로 고유한 (거래처, context_text) 조합만 골라서 find_embedding_candidates를
호출한다 — 이 테스트는 그 호출에 실제로 몇 개의 텍스트가 넘어가는지
monkeypatch로 가로채서 확인한다 (타이밍 추정이 아니라 직접 증명).
"""

import polars as pl
import pytest

import src.normalization_pipeline as pipeline
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
    not _EMBEDDING_AVAILABLE, reason=f"Embedding 모델을 사용할 수 없어 건너뜁니다: {_EMBEDDING_ERROR}"
)


def _institutions():
    nh = InstitutionMaster(institution_id=1, canonical_name="NH농협은행", active=True)
    nh.aliases = [InstitutionAlias(alias_text="농협은행", alias_type="ALIAS", active=True)]
    return [nh]


def test_duplicate_unresolved_rows_are_embedded_only_once(monkeypatch):
    """같은 (거래처, 문맥) 조합이 1,000번 반복돼도 Embedding은 고유값 개수만큼만 호출돼야 한다."""
    call_sizes = []
    original = pipeline.find_embedding_candidates

    def spy(vendor_texts, *args, **kwargs):
        call_sizes.append(len(vendor_texts))
        return original(vendor_texts, *args, **kwargs)

    monkeypatch.setattr(pipeline, "find_embedding_candidates", spy)

    # "OO농협"이라는 확정 못하는 표현을 1,000번 반복 (같은 vendor, 같은 context).
    n_repeats = 1000
    df = pl.DataFrame(
        {
            "거래처": ["OO농협"] * n_repeats,
            "context_text": ["OO농협 | 농산물 구매대금 지급 | 원재료 | 외상매입금"] * n_repeats,
        }
    )

    result_df, error = pipeline.apply_normalization(
        df, "거래처", _institutions(), fuzzy_auto_threshold=90.0, use_embedding=True, context_column="context_text"
    )

    assert error is None
    assert result_df.height == n_repeats
    # find_embedding_candidates에 넘어간 고유 벤더 텍스트 개수는 1개여야 한다
    # (1,000번이 아니라) — 이게 바로 "동일 표현 재계산 안 함"의 직접적인 증거다.
    assert call_sizes == [1]
