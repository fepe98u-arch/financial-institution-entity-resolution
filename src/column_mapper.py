"""회사마다 다른 분개장 컬럼명을 표준 필드에 매핑하고 context_text를 생성하는 모듈."""

import polars as pl

FIELD_LABELS = {
    "voucher_no": "전표번호",
    "voucher_date": "전표일자",
    "vendor": "거래처",
    "description": "적요",
    "account": "계정과목",
    "counter_account": "상대계정",
    "amount": "금액",
}

# 거래처는 금융기관 탐지의 핵심 정보이므로 필수, 나머지는 문맥 보강용 선택 항목.
REQUIRED_FIELDS = ["vendor"]

# context_text를 구성할 때 사용하는 필드와 순서.
CONTEXT_FIELDS = ["vendor", "description", "account", "counter_account"]


def validate_mapping(mapping: dict) -> list[str]:
    """필수 필드가 매핑되어 있는지 확인하고, 문제가 있으면 오류 메시지 목록을 반환한다."""
    errors = []
    for field in REQUIRED_FIELDS:
        if not mapping.get(field):
            errors.append(f"필수 항목이 비어 있습니다: {FIELD_LABELS[field]}")
    return errors


def build_context_text(df: pl.DataFrame, mapping: dict) -> pl.DataFrame:
    """매핑된 컬럼들을 ' | '로 이어붙인 context_text 컬럼을 추가한다.

    원본 컬럼은 그대로 유지하고 새 컬럼만 추가한다 (원본 데이터 보존).
    Python 반복문 없이 Polars expression으로 vectorized 처리한다.
    """
    errors = validate_mapping(mapping)
    if errors:
        raise ValueError(" / ".join(errors))

    parts = [
        pl.col(mapping[field]).cast(pl.Utf8).fill_null("")
        for field in CONTEXT_FIELDS
        if mapping.get(field)
    ]

    context_expr = parts[0]
    for part in parts[1:]:
        context_expr = context_expr + pl.lit(" | ") + part

    return df.with_columns(context_expr.alias("context_text"))
