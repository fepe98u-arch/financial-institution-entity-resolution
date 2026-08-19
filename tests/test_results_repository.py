"""processing_runs / normalization_results / human_reviews / feedback_labels 저장·조회 테스트.

PostgreSQL에 연결할 수 없으면 실패가 아니라 건너뜀(skip) 처리한다.
"""

import pytest
from sqlalchemy import delete, select

from src.database.connection import check_connection, get_engine, get_session
from src.database.models import CompletenessResult, FeedbackLabel, HumanReview, NormalizationResult, ProcessingRun
from src.database.repository import init_db

_connected, _message = check_connection()

pytestmark = pytest.mark.skipif(
    not _connected,
    reason=f"PostgreSQL에 연결할 수 없어 건너뜁니다: {_message}",
)


@pytest.fixture()
def db_session():
    init_db(get_engine())
    session = get_session()
    yield session
    session.close()


def _sample_rows():
    return [
        {
            "original_row_id": "V001",
            "detected_expression": "농협",
            "normalized_expression": "NH농협",
            "canonical_institution": "NH농협은행",
            "institution_id": None,
            "institution_type": "BANK",
            "normalization_method": "FUZZY",
            "top1_score": 90.0,
            "top2_candidate": None,
            "top2_score": None,
            "score_margin": None,
            "review_status": "AUTO",
            "context_text": "농협 | 대출이자 지급 | 이자비용 | 장기차입금",
            "reason": "테스트용",
            "user_confirmed": False,
        }
    ]


def _cleanup(session, run_id: int) -> None:
    result_ids = session.scalars(
        select(NormalizationResult.result_id).where(NormalizationResult.run_id == run_id)
    ).all()
    if result_ids:
        session.execute(delete(HumanReview).where(HumanReview.result_id.in_(result_ids)))
        session.execute(delete(NormalizationResult).where(NormalizationResult.result_id.in_(result_ids)))
    session.execute(delete(ProcessingRun).where(ProcessingRun.run_id == run_id))
    session.commit()


def test_start_and_complete_processing_run(db_session):
    from src.database.results_repository import complete_processing_run, start_processing_run

    run = start_processing_run(db_session, "pytest_sample.csv", "csv", total_rows=1)
    assert run.status == "RUNNING"

    complete_processing_run(db_session, run.run_id, processing_seconds=1.23)
    db_session.refresh(run)
    assert run.status == "COMPLETED"
    assert run.processing_seconds is not None

    _cleanup(db_session, run.run_id)


def test_save_and_query_normalization_results(db_session):
    from src.database.results_repository import (
        find_result_ids,
        get_normalization_results,
        save_normalization_results,
        start_processing_run,
    )

    run = start_processing_run(db_session, "pytest_sample.csv", "csv", total_rows=1)
    save_normalization_results(db_session, run.run_id, _sample_rows())

    results = get_normalization_results(db_session, run.run_id)
    assert len(results) == 1
    assert results[0].detected_expression == "농협"

    ids = find_result_ids(db_session, run.run_id, "농협", "농협 | 대출이자 지급 | 이자비용 | 장기차입금")
    assert len(ids) == 1

    _cleanup(db_session, run.run_id)


def test_apply_review_and_add_human_review_and_feedback(db_session):
    from src.database.results_repository import (
        add_feedback_label,
        add_human_review,
        apply_review_to_results,
        find_result_ids,
        save_normalization_results,
        start_processing_run,
    )

    run = start_processing_run(db_session, "pytest_sample.csv", "csv", total_rows=1)
    save_normalization_results(db_session, run.run_id, _sample_rows())
    result_ids = find_result_ids(db_session, run.run_id, "농협", "농협 | 대출이자 지급 | 이자비용 | 장기차입금")

    apply_review_to_results(db_session, result_ids, "AUTO", "NH농협은행", None, normalization_method="HUMAN")

    review = add_human_review(
        db_session,
        result_ids[0],
        model_prediction="NH농협은행",
        user_decision="NH농협은행",
        review_action="APPROVE",
    )
    assert review.review_id is not None

    label = add_feedback_label(
        db_session,
        original_expression="농협",
        context_text="농협 | 대출이자 지급 | 이자비용 | 장기차입금",
        model_prediction="NH농협은행",
        confirmed_label="NH농협은행",
        source_review_id=review.review_id,
    )
    assert label.label_id is not None

    db_session.execute(delete(FeedbackLabel).where(FeedbackLabel.label_id == label.label_id))
    db_session.commit()
    _cleanup(db_session, run.run_id)


def test_save_and_query_completeness_results(db_session):
    from src.database.results_repository import save_completeness_results, start_processing_run

    run = start_processing_run(db_session, "pytest_completeness.csv", "csv", total_rows=1)
    rows = [
        {
            "institution_id": None,
            "canonical_name": "KB국민은행",
            "company_list_exists": False,
            "journal_detected": True,
            "journal_count": 3,
            "total_amount": 15000,
            "review_status": "ADDITIONAL_CANDIDATE",
        }
    ]
    save_completeness_results(db_session, run.run_id, rows)

    results = list(db_session.scalars(select(CompletenessResult).where(CompletenessResult.run_id == run.run_id)))
    assert len(results) == 1
    assert results[0].canonical_name == "KB국민은행"
    assert results[0].journal_count == 3

    # 같은 run에 다시 저장하면 이전 결과를 지우고 새로 저장해야 한다 (재실행 지원).
    save_completeness_results(db_session, run.run_id, rows)
    results_after = list(
        db_session.scalars(select(CompletenessResult).where(CompletenessResult.run_id == run.run_id))
    )
    assert len(results_after) == 1

    db_session.execute(delete(CompletenessResult).where(CompletenessResult.run_id == run.run_id))
    db_session.commit()
    _cleanup(db_session, run.run_id)


def test_add_and_list_performance_log(db_session):
    from src.database.models import PerformanceLog
    from src.database.results_repository import add_performance_log, start_processing_run

    run = start_processing_run(db_session, "pytest_perf.csv", "csv", total_rows=300000)
    log = add_performance_log(
        db_session,
        run.run_id,
        total_rows=300000,
        fast_path_count=290000,
        alias_count=0,
        fuzzy_count=0,
        embedding_count=0,
        context_rerank_count=10000,
        manual_review_count=10000,
        unresolved_count=0,
        cache_hit_count=299977,
        processing_seconds=11.73,
    )
    assert log.performance_id is not None

    logs = [r for r in db_session.query(PerformanceLog).all() if r.run_id == run.run_id]
    assert len(logs) == 1
    assert logs[0].total_rows == 300000

    db_session.execute(delete(PerformanceLog).where(PerformanceLog.run_id == run.run_id))
    db_session.commit()
    _cleanup(db_session, run.run_id)


def test_load_run_as_dataframe_restores_saved_columns(db_session):
    """브라우저/서버를 껐다 켜도 저장된 실행을 다시 DataFrame으로 불러올 수 있어야 한다."""
    from src.database.results_repository import load_run_as_dataframe, save_normalization_results, start_processing_run

    run = start_processing_run(db_session, "pytest_sample.csv", "csv", total_rows=1)
    save_normalization_results(db_session, run.run_id, _sample_rows())

    loaded = load_run_as_dataframe(db_session, run.run_id)

    assert loaded.height == 1
    row = loaded.to_dicts()[0]
    assert row["detected_expression"] == "농협"
    assert row["canonical_institution"] == "NH농협은행"
    assert row["normalization_method"] == "FUZZY"
    assert row["review_status"] == "AUTO"
    assert row["context_text"] == "농협 | 대출이자 지급 | 이자비용 | 장기차입금"
    assert row["top1_score"] == pytest.approx(90.0)

    _cleanup(db_session, run.run_id)


def test_load_run_as_dataframe_empty_for_unknown_run():
    from src.database.connection import get_session
    from src.database.results_repository import load_run_as_dataframe

    session = get_session()
    try:
        loaded = load_run_as_dataframe(session, run_id=-1)
        assert loaded.height == 0
    finally:
        session.close()


def test_delete_processing_run_cascades_but_keeps_feedback_labels(db_session):
    """실행을 지우면 결과/Human Review는 지워지지만, feedback_labels는 남아야 한다
    (향후 모델 개선용으로 계속 쌓아두는 목적이기 때문 -- source_review_id만 끊긴다)."""
    from src.database.results_repository import (
        add_feedback_label,
        add_human_review,
        delete_processing_run,
        find_result_ids,
        save_normalization_results,
        start_processing_run,
    )

    run = start_processing_run(db_session, "pytest_delete.csv", "csv", total_rows=1)
    save_normalization_results(db_session, run.run_id, _sample_rows())
    result_ids = find_result_ids(db_session, run.run_id, "농협", "농협 | 대출이자 지급 | 이자비용 | 장기차입금")

    review = add_human_review(db_session, result_ids[0], "NH농협은행", "NH농협은행", "APPROVE")
    review_id = review.review_id
    label = add_feedback_label(
        db_session,
        original_expression="농협",
        context_text="농협 | 대출이자 지급 | 이자비용 | 장기차입금",
        model_prediction="NH농협은행",
        confirmed_label="NH농협은행",
        source_review_id=review_id,
    )
    label_id = label.label_id

    deleted_count = delete_processing_run(db_session, run.run_id)
    assert deleted_count == 1

    assert db_session.get(ProcessingRun, run.run_id) is None
    assert db_session.get(NormalizationResult, result_ids[0]) is None
    assert db_session.get(HumanReview, review_id) is None

    remaining_label = db_session.get(FeedbackLabel, label_id)
    assert remaining_label is not None
    assert remaining_label.confirmed_label == "NH농협은행"
    assert remaining_label.source_review_id is None

    db_session.execute(delete(FeedbackLabel).where(FeedbackLabel.label_id == label_id))
    db_session.commit()
