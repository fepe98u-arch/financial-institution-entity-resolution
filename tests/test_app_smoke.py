"""Streamlit AppTest를 이용한 화면 동작 스모크 테스트.

브라우저 없이 app.py를 실제로 실행해서, 샘플 데이터 생성 -> 컬럼 매핑 ->
context_text 생성까지 에러 없이 동작하는지 확인한다.
"""

import pytest
from streamlit.testing.v1 import AppTest

from src.database.connection import check_connection

APP_TIMEOUT = 20
_DB_CONNECTED, _ = check_connection()


def test_dashboard_loads_without_error():
    at = AppTest.from_file("app.py")
    at.run(timeout=APP_TIMEOUT)
    assert not at.exception


def test_generate_sample_data():
    at = AppTest.from_file("app.py")
    at.run(timeout=APP_TIMEOUT)

    at.sidebar.radio[0].set_value("분개장 업로드").run(timeout=APP_TIMEOUT)
    at.button[0].click().run(timeout=APP_TIMEOUT)  # "샘플 분개 생성" 버튼

    assert not at.exception
    assert any("생성 완료" in s.value for s in at.success)


def test_column_mapping_builds_context_text():
    at = AppTest.from_file("app.py")
    at.run(timeout=APP_TIMEOUT)

    at.sidebar.radio[0].set_value("분개장 업로드").run(timeout=APP_TIMEOUT)
    at.button[0].click().run(timeout=APP_TIMEOUT)

    at.sidebar.radio[0].set_value("컬럼 Mapping").run(timeout=APP_TIMEOUT)
    # selectbox 순서: 전표번호, 전표일자, 거래처*, 적요, 계정과목, 상대계정, 금액
    at.selectbox[2].set_value("거래처").run(timeout=APP_TIMEOUT)
    at.selectbox[3].set_value("적요").run(timeout=APP_TIMEOUT)
    at.selectbox[4].set_value("계정과목").run(timeout=APP_TIMEOUT)
    at.selectbox[5].set_value("상대계정").run(timeout=APP_TIMEOUT)

    at.button[0].click().run(timeout=APP_TIMEOUT)  # "context_text 생성 및 미리보기" 버튼

    assert not at.exception
    assert any("context_text" in s.value for s in at.success)


@pytest.mark.parametrize("page_name", ["금융기관 Master", "Alias Master", "Database 상태"])
def test_db_pages_load_without_crashing(page_name):
    """PostgreSQL이 연결되어 있지 않아도 이 화면들이 에러 없이 '연결 필요' 안내를 보여줘야 한다."""
    at = AppTest.from_file("app.py")
    at.run(timeout=APP_TIMEOUT)
    at.sidebar.radio[0].set_value(page_name).run(timeout=APP_TIMEOUT)

    assert not at.exception
    if not _DB_CONNECTED:
        messages = [w.value for w in at.warning] + [e.value for e in at.error]
        assert any("PostgreSQL" in m or "Not Connected" in m or "연결" in m for m in messages)


@pytest.mark.skipif(not _DB_CONNECTED, reason="PostgreSQL 연결 없이는 정규화 화면을 끝까지 테스트할 수 없어 건너뜁니다.")
def test_normalization_end_to_end_via_ui():
    """마스터 시딩 -> 샘플 생성 -> 컬럼 매핑 -> 정규화 실행까지 화면 흐름 전체를 확인한다."""
    at = AppTest.from_file("app.py")
    at.run(timeout=APP_TIMEOUT)

    at.sidebar.radio[0].set_value("금융기관 Master").run(timeout=APP_TIMEOUT)
    at.button[0].click().run(timeout=APP_TIMEOUT)  # 샘플 마스터 데이터 추가 (이미 있으면 건너뜀)

    at.sidebar.radio[0].set_value("분개장 업로드").run(timeout=APP_TIMEOUT)
    at.button[0].click().run(timeout=APP_TIMEOUT)  # 샘플 분개 생성

    at.sidebar.radio[0].set_value("컬럼 Mapping").run(timeout=APP_TIMEOUT)
    at.selectbox[2].set_value("거래처").run(timeout=APP_TIMEOUT)
    at.selectbox[3].set_value("적요").run(timeout=APP_TIMEOUT)
    at.selectbox[4].set_value("계정과목").run(timeout=APP_TIMEOUT)
    at.selectbox[5].set_value("상대계정").run(timeout=APP_TIMEOUT)
    at.button[0].click().run(timeout=APP_TIMEOUT)

    at.sidebar.radio[0].set_value("금융기관 정규화").run(timeout=APP_TIMEOUT)
    at.button[0].click().run(timeout=APP_TIMEOUT)  # 정규화 실행

    assert not at.exception
    assert any("FAST PATH 정규화를 완료" in s.value for s in at.success)
