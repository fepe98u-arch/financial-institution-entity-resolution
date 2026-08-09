"""Streamlit AppTest를 이용한 화면 동작 스모크 테스트.

브라우저 없이 app.py를 실제로 실행해서, 샘플 데이터 생성 -> 컬럼 매핑 ->
context_text 생성까지 에러 없이 동작하는지 확인한다.
"""

from streamlit.testing.v1 import AppTest

APP_TIMEOUT = 20


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
