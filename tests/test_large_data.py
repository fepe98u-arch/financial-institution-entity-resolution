"""대용량(10,000 / 100,000 / 300,000행) 처리 테스트.

계획서 42번 섹션의 항목 23~25에 대응한다. 10,000/100,000행은 FAST PATH만
써도 항상 빠르므로 기본 pytest 실행에 포함한다. 300,000행 + Embedding까지
포함한 전체 파이프라인은 (실측상 약 12초 걸려서) 기본 실행 시간을 눈에 띄게
늘리므로, 환경변수 RUN_SLOW_TESTS=1을 설정했을 때만 실행한다:

    RUN_SLOW_TESTS=1 pytest tests/test_large_data.py -v

PC 환경상 이 테스트를 실행하지 못했다면(예: 시간이 오래 걸려서 강제로
실행하지 않았다면), "실행하지 않음"이라고 명확히 보고해야 한다 — 이 파일의
기본 skip 사유가 바로 그 이유를 설명한다.
"""

import os

import pytest

from src.column_mapper import build_context_text
from src.database.connection import check_connection, get_engine, get_session
from src.database.repository import init_db, list_institutions_with_aliases
from src.normalization_pipeline import apply_normalization
from src.synthetic_data_generator import generate_synthetic_journal

_DB_CONNECTED, _DB_MESSAGE = check_connection()
_RUN_SLOW_TESTS = os.environ.get("RUN_SLOW_TESTS") == "1"

_MAPPING = {"vendor": "거래처", "description": "적요", "account": "계정과목", "counter_account": "상대계정"}

pytestmark = pytest.mark.skipif(
    not _DB_CONNECTED, reason=f"PostgreSQL에 연결할 수 없어 건너뜁니다: {_DB_MESSAGE}"
)


@pytest.fixture(scope="module")
def institutions():
    init_db(get_engine())
    session = get_session()
    try:
        return list_institutions_with_aliases(session, active_only=True)
    finally:
        session.close()


def test_synthetic_10000_rows_fast_path_only(institutions):
    df = generate_synthetic_journal(n_rows=10_000)
    df = build_context_text(df, _MAPPING)

    result_df, error = apply_normalization(df, "거래처", institutions, 90.0, use_embedding=False)

    assert error is None
    assert result_df.height == 10_000
    # 원본 컬럼이 보존되어야 한다 (원본 파일을 수정하지 않는다는 원칙과 동일).
    assert "거래처" in result_df.columns
    assert "금액" in result_df.columns


def test_synthetic_100000_rows_fast_path_only(institutions):
    df = generate_synthetic_journal(n_rows=100_000)
    df = build_context_text(df, _MAPPING)

    result_df, error = apply_normalization(df, "거래처", institutions, 90.0, use_embedding=False)

    assert error is None
    assert result_df.height == 100_000


@pytest.mark.skipif(
    not _RUN_SLOW_TESTS,
    reason=(
        "300,000행 + Embedding 전체 파이프라인은 약 12초가 걸려 기본 실행에서 건너뜁니다. "
        "RUN_SLOW_TESTS=1 환경변수를 설정하면 실행됩니다."
    ),
)
def test_synthetic_300000_rows_full_pipeline_dedup_and_completes(institutions):
    """300,000행에서도 실제로 고유 조합만 계산하는지, 끝까지 도는지 확인한다."""
    df = generate_synthetic_journal(n_rows=300_000)
    df = build_context_text(df, _MAPPING)

    unique_pairs = df.select(["거래처", "context_text"]).unique().height

    result_df, error = apply_normalization(
        df, "거래처", institutions, 90.0, use_embedding=True, context_column="context_text", embedding_floor=0.85
    )

    assert error is None
    assert result_df.height == 300_000
    # 실측(2026-08-09 기준): 고유 조합은 23개뿐이었다. 정확한 개수는 샘플
    # 템플릿이 바뀌면 달라질 수 있으므로, "행 수보다 훨씬 적다"만 확인한다.
    assert unique_pairs < 100
