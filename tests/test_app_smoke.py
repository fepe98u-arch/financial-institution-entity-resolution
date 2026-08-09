"""Streamlit AppTest를 이용한 화면 동작 스모크 테스트.

브라우저 없이 app.py를 실제로 실행해서, 샘플 데이터 생성 -> 컬럼 매핑 ->
context_text 생성까지 에러 없이 동작하는지 확인한다.
"""

import pytest
from sqlalchemy import delete, select
from streamlit.testing.v1 import AppTest

from src.database.connection import check_connection, get_session
from src.database.models import FeedbackLabel, HumanReview, NormalizationResult, ProcessingRun

APP_TIMEOUT = 20
_DB_CONNECTED, _ = check_connection()


def _cleanup_run(run_id: int | None) -> None:
    """AppTest가 만든 processing_run과 그에 딸린 결과/리뷰/피드백을 정리한다."""
    if run_id is None:
        return
    session = get_session()
    try:
        result_ids = list(
            session.scalars(select(NormalizationResult.result_id).where(NormalizationResult.run_id == run_id))
        )
        if result_ids:
            review_ids = list(
                session.scalars(select(HumanReview.review_id).where(HumanReview.result_id.in_(result_ids)))
            )
            if review_ids:
                session.execute(delete(FeedbackLabel).where(FeedbackLabel.source_review_id.in_(review_ids)))
                session.execute(delete(HumanReview).where(HumanReview.review_id.in_(review_ids)))
            session.execute(delete(NormalizationResult).where(NormalizationResult.result_id.in_(result_ids)))
        session.execute(delete(ProcessingRun).where(ProcessingRun.run_id == run_id))
        session.commit()
    finally:
        session.close()


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
    assert any("정규화를 완료" in s.value for s in at.success)

    _cleanup_run(at.session_state["current_run_id"] if "current_run_id" in at.session_state else None)


@pytest.mark.skipif(not _DB_CONNECTED, reason="PostgreSQL 연결 없이는 Human Review 화면을 끝까지 테스트할 수 없어 건너뜁니다.")
def test_human_review_approve_via_ui():
    """정규화 실행 후 Human Review 화면에서 승인 버튼까지 눌러서 실제로 반영되는지 확인한다."""
    at = AppTest.from_file("app.py")
    at.run(timeout=APP_TIMEOUT)

    at.sidebar.radio[0].set_value("금융기관 Master").run(timeout=APP_TIMEOUT)
    at.button[0].click().run(timeout=APP_TIMEOUT)

    at.sidebar.radio[0].set_value("분개장 업로드").run(timeout=APP_TIMEOUT)
    at.button[0].click().run(timeout=APP_TIMEOUT)

    at.sidebar.radio[0].set_value("컬럼 Mapping").run(timeout=APP_TIMEOUT)
    at.selectbox[2].set_value("거래처").run(timeout=APP_TIMEOUT)
    at.selectbox[3].set_value("적요").run(timeout=APP_TIMEOUT)
    at.selectbox[4].set_value("계정과목").run(timeout=APP_TIMEOUT)
    at.selectbox[5].set_value("상대계정").run(timeout=APP_TIMEOUT)
    at.button[0].click().run(timeout=APP_TIMEOUT)

    at.sidebar.radio[0].set_value("금융기관 정규화").run(timeout=APP_TIMEOUT)
    at.button[0].click().run(timeout=APP_TIMEOUT)

    at.sidebar.radio[0].set_value("Human Review").run(timeout=APP_TIMEOUT)
    assert not at.exception

    if not at.radio:
        # 검토 필요 항목이 하나도 없는 드문 경우 (샘플 데이터 특성상 거의 발생하지 않음)
        _cleanup_run(at.session_state["current_run_id"] if "current_run_id" in at.session_state else None)
        return

    at.radio[0].set_value("승인 (제안 기관으로 확정)").run(timeout=APP_TIMEOUT)
    at.button[0].click().run(timeout=APP_TIMEOUT)

    assert not at.exception
    assert any("반영했습니다" in s.value for s in at.success)

    _cleanup_run(at.session_state["current_run_id"] if "current_run_id" in at.session_state else None)
