"""정규화/완전성 비교 결과를 여러 시트가 있는 Excel 파일로 내보낸다.

Polars의 write_excel()은 내부적으로 xlsxwriter를 사용한다. 여러 시트를 한
파일에 담기 위해 xlsxwriter Workbook을 직접 만들고, 같은 workbook 객체를
계속 재사용해서 write_excel(workbook=...)을 호출한다 (Polars 공식 문서가
안내하는 다중 시트 작성 방식).

원본 분개 파일은 절대 수정하지 않는다 — 이 함수는 항상 새 bytes를 만들어
반환하고, 저장 여부는 호출한 쪽(Streamlit 다운로드 버튼)이 결정한다.
"""

import io

import polars as pl
import xlsxwriter

MAX_SHEET_NAME_LENGTH = 31  # Excel 시트 이름 길이 제한


def build_excel_report(sheets: dict[str, pl.DataFrame]) -> bytes:
    """시트 이름 -> DataFrame 딕셔너리를 받아 하나의 Excel 파일(bytes)로 만든다.

    빈 DataFrame은 "데이터 없음" 안내 한 줄로 대체한다 (완전히 빈 시트는
    xlsxwriter가 오류를 내기 때문).
    """
    if not sheets:
        raise ValueError("최소 한 개의 시트가 필요합니다.")

    buffer = io.BytesIO()
    workbook = xlsxwriter.Workbook(buffer, {"in_memory": True})
    try:
        for name, df in sheets.items():
            safe_name = name[:MAX_SHEET_NAME_LENGTH]
            if df.height == 0:
                df = pl.DataFrame({"안내": ["데이터가 없습니다."]})
            df.write_excel(workbook=workbook, worksheet=safe_name)
    finally:
        workbook.close()

    return buffer.getvalue()
