"""Streamlit AppTest를 이용한 화면 동작 스모크 테스트.

브라우저 없이 app.py를 실제로 실행해서, 샘플 데이터 생성 -> 컬럼 매핑 ->
context_text 생성까지 에러 없이 동작하는지 확인한다.
"""

import os

import pytest
from sqlalchemy import delete, select
from streamlit.testing.v1 import AppTest

import src.config_loader  # noqa: F401  (import 시 .env를 로딩한다)
from src.database.connection import check_connection, get_session
from src.database.models import (
    CompletenessResult,
    FeedbackLabel,
    HumanReview,
    NormalizationResult,
    PerformanceLog,
    ProcessingRun,
)

APP_TIMEOUT = 20
_DB_CONNECTED, _ = check_connection()
_APP_PASSWORD = os.getenv("APP_PASSWORD")


def _login(at: AppTest) -> None:
    """비밀번호 게이트를 통과시킨다 — 이후에야 사이드바(메뉴)가 나타난다."""
    if not _APP_PASSWORD:
        pytest.skip("APP_PASSWORD가 .env에 없어 화면 흐름 테스트를 진행할 수 없습니다.")
    at.text_input[0].set_value(_APP_PASSWORD).run(timeout=APP_TIMEOUT)
    at.button[0].click().run(timeout=APP_TIMEOUT)


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
        session.execute(delete(CompletenessResult).where(CompletenessResult.run_id == run_id))
        session.execute(delete(PerformanceLog).where(PerformanceLog.run_id == run_id))
        session.execute(delete(ProcessingRun).where(ProcessingRun.run_id == run_id))
        session.commit()
    finally:
        session.close()


def test_login_screen_loads_without_error():
    """로그인 화면 자체가 에러 없이 뜨는지 확인한다 (비밀번호 입력 전 상태)."""
    at = AppTest.from_file("app.py")
    at.run(timeout=APP_TIMEOUT)
    assert not at.exception
    assert len(at.text_input) > 0
    assert len(at.sidebar.radio) == 0  # 로그인 전에는 메뉴가 보이면 안 됨


def test_dashboard_loads_without_error():
    at = AppTest.from_file("app.py")
    at.run(timeout=APP_TIMEOUT)
    _login(at)
    assert not at.exception


def test_generate_sample_data():
    at = AppTest.from_file("app.py")
    at.run(timeout=APP_TIMEOUT)
    _login(at)

    at.sidebar.radio[0].set_value("분개장 업로드").run(timeout=APP_TIMEOUT)
    at.button[0].click().run(timeout=APP_TIMEOUT)  # "샘플 분개 생성" 버튼

    assert not at.exception
    assert any("생성 완료" in s.value for s in at.success)


def test_column_mapping_builds_context_text():
    at = AppTest.from_file("app.py")
    at.run(timeout=APP_TIMEOUT)
    _login(at)

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
    _login(at)
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
    _login(at)

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
    _login(at)

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


@pytest.mark.skipif(not _DB_CONNECTED, reason="PostgreSQL 연결 없이는 완전성 비교 화면을 끝까지 테스트할 수 없어 건너뜁니다.")
def test_completeness_comparison_finds_additional_candidate_via_ui():
    """샘플 회사 목록에서 일부러 뺀 KB국민은행이 '추가 검토 후보(B-A)'로 잡히는지 화면으로 확인한다."""
    at = AppTest.from_file("app.py")
    at.run(timeout=APP_TIMEOUT)
    _login(at)

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

    at.sidebar.radio[0].set_value("회사 금융기관 목록").run(timeout=APP_TIMEOUT)
    at.button[0].click().run(timeout=APP_TIMEOUT)  # 샘플 회사 목록 생성 (NH농협은행/신한은행만)

    at.sidebar.radio[0].set_value("완전성 비교").run(timeout=APP_TIMEOUT)
    at.button[0].click().run(timeout=APP_TIMEOUT)  # 완전성 비교 실행

    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics.get("B - A (추가 검토 후보)") == "1"

    run_id = at.session_state["current_run_id"] if "current_run_id" in at.session_state else None
    _cleanup_run(run_id)


@pytest.mark.skipif(not _DB_CONNECTED, reason="PostgreSQL 연결 없이는 모델 성능 화면을 끝까지 테스트할 수 없어 건너뜁니다.")
def test_model_performance_runs_all_variants_via_ui():
    at = AppTest.from_file("app.py")
    at.run(timeout=APP_TIMEOUT)
    _login(at)

    at.sidebar.radio[0].set_value("금융기관 Master").run(timeout=APP_TIMEOUT)
    at.button[0].click().run(timeout=APP_TIMEOUT)

    at.sidebar.radio[0].set_value("모델 성능").run(timeout=APP_TIMEOUT)
    at.button[0].click().run(timeout=60)

    assert not at.exception
    assert len(at.dataframe) > 0


@pytest.mark.skipif(not _DB_CONNECTED, reason="PostgreSQL 연결 없이는 처리 성능 화면을 끝까지 테스트할 수 없어 건너뜁니다.")
def test_processing_performance_measures_real_timing_via_ui():
    at = AppTest.from_file("app.py")
    at.run(timeout=APP_TIMEOUT)
    _login(at)

    at.sidebar.radio[0].set_value("금융기관 Master").run(timeout=APP_TIMEOUT)
    at.button[0].click().run(timeout=APP_TIMEOUT)

    at.sidebar.radio[0].set_value("처리 성능").run(timeout=APP_TIMEOUT)
    at.number_input[0].set_value(10000).run(timeout=APP_TIMEOUT)
    at.button[0].click().run(timeout=60)

    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics.get("행 수") == "10,000"
    # 고유 조합 수가 전체 행 수보다 훨씬 적어야 한다 (dedup/cache 효과 실제 확인).
    unique_pairs = int(metrics["고유 (거래처,문맥) 조합"].replace(",", ""))
    assert unique_pairs < 100

    run_id = None
    session = get_session()
    try:
        run = session.query(ProcessingRun).filter(ProcessingRun.file_name == "perf_test_10000rows.csv").first()
        if run is not None:
            run_id = run.run_id
    finally:
        session.close()
    if run_id is not None:
        performance_session = get_session()
        try:
            performance_session.execute(delete(PerformanceLog).where(PerformanceLog.run_id == run_id))
            performance_session.commit()
        finally:
            performance_session.close()
        _cleanup_run(run_id)
