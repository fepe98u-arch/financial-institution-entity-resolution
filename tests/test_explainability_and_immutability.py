"""설명가능성(계획서 30번 섹션)과 원본 보존(계획서 14/43번 섹션) 원칙을 직접 검증한다.

- 모든 정규화 결과는 "왜 이렇게 판단했는지"를 reason에 반드시 남겨야 한다.
- 원본 DataFrame(업로드된 파일에서 읽은 것)은 정규화/문맥 생성 과정에서
  절대 바뀌면 안 된다 (새 DataFrame을 반환할 뿐, 원본을 고치지 않는다).
"""

import polars as pl

from src.column_mapper import build_context_text
from src.database.models import InstitutionAlias, InstitutionMaster
from src.normalization_pipeline import apply_normalization

THRESHOLD = 90.0


def _institutions():
    nh = InstitutionMaster(institution_id=1, canonical_name="NH농협은행", active=True)
    nh.aliases = [InstitutionAlias(alias_text="농협은행", alias_type="ALIAS", active=True)]
    return [nh]


def test_every_result_row_has_a_non_empty_reason():
    df = pl.DataFrame({"거래처": ["NH농협은행", "농협은행", "테스트전자"]})
    result_df, _ = apply_normalization(df, "거래처", _institutions(), THRESHOLD, use_embedding=False)

    reasons = result_df["reason"].to_list()
    assert all(r is not None and len(r) > 0 for r in reasons)


def test_apply_normalization_does_not_mutate_original_dataframe():
    original_df = pl.DataFrame({"거래처": ["NH농협은행", "테스트전자"], "금액": [1000, 2000]})
    original_columns = list(original_df.columns)
    original_values = original_df.to_dicts()

    apply_normalization(original_df, "거래처", _institutions(), THRESHOLD, use_embedding=False)

    # 원본 df 객체 자체는 호출 전과 완전히 동일해야 한다 (새 컬럼이 추가되지 않음).
    assert original_df.columns == original_columns
    assert original_df.to_dicts() == original_values


def test_build_context_text_does_not_mutate_original_dataframe():
    original_df = pl.DataFrame({"vendor_col": ["농협은행"], "desc_col": ["대출이자 지급"]})
    original_columns = list(original_df.columns)

    build_context_text(original_df, {"vendor": "vendor_col", "description": "desc_col"})

    assert original_df.columns == original_columns  # context_text가 원본에 추가되면 안 됨
