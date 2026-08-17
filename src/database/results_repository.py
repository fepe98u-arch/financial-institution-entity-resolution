"""정규화 실행 이력(processing_runs), 분석 결과(normalization_results),
Human Review(human_reviews), Feedback Label(feedback_labels), 완전성 비교
결과(completeness_results)에 대한 저장/조회 함수.

institution_master/institution_alias는 repository.py에서, 실행 결과와 사람의
판단은 이 파일에서 다룬다 (역할 분리).

normalization_results는 ORM 객체를 하나씩 만들어 session.add_all()로 저장하지
않는다 — 실측해보니 100만 행 기준 그 방식은 140초, SQLAlchemy Core 일괄
INSERT로 바꿔도 130초로 큰 차이가 없었다. psycopg의 COPY 프로토콜로 바꾼 뒤
다시 실측한 결과는 README에 실제 값을 적어뒀다.
"""

from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from src.database.models import (
    CompletenessResult,
    FeedbackLabel,
    HumanReview,
    NormalizationResult,
    PerformanceLog,
    ProcessingRun,
)

# ---------------------------------------------------------------------------
# processing_runs
# ---------------------------------------------------------------------------


def start_processing_run(session: Session, file_name: str, file_type: str, total_rows: int) -> ProcessingRun:
    run = ProcessingRun(
        file_name=file_name,
        file_type=file_type,
        total_rows=total_rows,
        status="RUNNING",
        started_at=datetime.now(timezone.utc),
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def complete_processing_run(session: Session, run_id: int, processing_seconds: float, status: str = "COMPLETED") -> None:
    run = session.get(ProcessingRun, run_id)
    if run is None:
        raise ValueError(f"run_id={run_id} 를 찾을 수 없습니다.")
    run.status = status
    run.completed_at = datetime.now(timezone.utc)
    run.processing_seconds = processing_seconds
    session.commit()


def list_processing_runs(session: Session, limit: int = 20) -> list[ProcessingRun]:
    stmt = select(ProcessingRun).order_by(ProcessingRun.created_at.desc()).limit(limit)
    return list(session.scalars(stmt))


# ---------------------------------------------------------------------------
# normalization_results
# ---------------------------------------------------------------------------


def save_normalization_results(session: Session, run_id: int, rows: list[dict]) -> int:
    """정규화 결과를 run_id에 연결해서 한 번에 저장한다. 저장한 행 수를 반환한다.

    rows의 각 dict는 NormalizationResult 컬럼명과 일치하는 키를 가져야 한다
    (run_id는 이 함수가 채운다). PostgreSQL의 COPY 프로토콜을 쓴다 — 일반
    INSERT(한 건씩이든 Core 일괄이든)는 행마다 SQL 파싱/플래닝 비용이 들지만,
    COPY는 스트리밍이라 그 비용이 없다. 실측 결과(100만 행)는 이 파일 상단
    docstring과 README에 남겨뒀다.
    """
    if not rows:
        return 0

    data_columns = list(rows[0].keys())
    columns = ["run_id", *data_columns]
    column_list_sql = ", ".join(columns)

    raw_connection = session.connection().connection.dbapi_connection
    with raw_connection.cursor() as cursor:
        with cursor.copy(f"COPY normalization_results ({column_list_sql}) FROM STDIN") as copy:
            for row in rows:
                copy.write_row([run_id, *(row[c] for c in data_columns)])
    session.commit()
    return len(rows)


def get_normalization_results(
    session: Session, run_id: int, review_status: str | None = None
) -> list[NormalizationResult]:
    stmt = select(NormalizationResult).where(NormalizationResult.run_id == run_id)
    if review_status is not None:
        stmt = stmt.where(NormalizationResult.review_status == review_status)
    return list(session.scalars(stmt))


def find_result_ids(session: Session, run_id: int, detected_expression: str, context_text: str | None) -> list[int]:
    """같은 (거래처 표현, 문맥)으로 저장된 모든 결과 행의 result_id를 찾는다.

    같은 표현이 여러 원본 분개 행에 반복되면, 하나의 Human Review 판단을
    그 행들 전체에 반영해야 하기 때문에 여러 개가 나올 수 있다.
    """
    stmt = select(NormalizationResult.result_id).where(
        NormalizationResult.run_id == run_id,
        NormalizationResult.detected_expression == detected_expression,
    )
    if context_text is not None:
        stmt = stmt.where(NormalizationResult.context_text == context_text)
    return list(session.scalars(stmt))


def apply_review_to_results(
    session: Session,
    result_ids: list[int],
    review_status: str,
    canonical_institution: str | None,
    institution_id: int | None,
    normalization_method: str = "HUMAN",
) -> None:
    if not result_ids:
        return
    stmt = select(NormalizationResult).where(NormalizationResult.result_id.in_(result_ids))
    for result in session.scalars(stmt):
        result.review_status = review_status
        result.canonical_institution = canonical_institution
        result.institution_id = institution_id
        result.normalization_method = normalization_method
        result.user_confirmed = True
    session.commit()


# ---------------------------------------------------------------------------
# human_reviews
# ---------------------------------------------------------------------------


def add_human_review(
    session: Session,
    result_id: int,
    model_prediction: str | None,
    user_decision: str | None,
    review_action: str,
    review_note: str | None = None,
) -> HumanReview:
    review = HumanReview(
        result_id=result_id,
        model_prediction=model_prediction,
        user_decision=user_decision,
        review_action=review_action,
        review_note=review_note,
    )
    session.add(review)
    session.commit()
    session.refresh(review)
    return review


def add_human_reviews_bulk(
    session: Session,
    result_ids: list[int],
    model_prediction: str | None,
    user_decision: str | None,
    review_action: str,
    review_note: str | None = None,
) -> list[HumanReview]:
    """result_ids 전체에 같은 판단을 한 번에 저장한다 (건마다 commit하지 않음).

    같은 표현이 반복되는 원본 행이 많으면(예: 100만 행 데이터에서 자주 나오는
    거래처명은 result_id가 수만 개일 수 있다) add_human_review를 result_id마다
    호출해서 매번 commit하면 매우 느려진다 — add_all + commit 한 번으로 바꾼다.
    """
    if not result_ids:
        return []
    reviews = [
        HumanReview(
            result_id=result_id,
            model_prediction=model_prediction,
            user_decision=user_decision,
            review_action=review_action,
            review_note=review_note,
        )
        for result_id in result_ids
    ]
    session.add_all(reviews)
    session.commit()
    return reviews


def count_human_reviews(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(HumanReview)) or 0


# ---------------------------------------------------------------------------
# feedback_labels
# ---------------------------------------------------------------------------


def add_feedback_label(
    session: Session,
    original_expression: str,
    context_text: str | None,
    model_prediction: str | None,
    confirmed_label: str,
    source_review_id: int | None = None,
) -> FeedbackLabel:
    label = FeedbackLabel(
        original_expression=original_expression,
        context_text=context_text,
        model_prediction=model_prediction,
        confirmed_label=confirmed_label,
        source_review_id=source_review_id,
    )
    session.add(label)
    session.commit()
    session.refresh(label)
    return label


def count_feedback_labels(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(FeedbackLabel)) or 0


# ---------------------------------------------------------------------------
# completeness_results (Phase 7)
# ---------------------------------------------------------------------------


def save_completeness_results(session: Session, run_id: int, rows: list[dict]) -> list[CompletenessResult]:
    """완전성 비교 결과(회사 제출 목록 vs 분개장 발견 결과)를 run_id에 연결해서 저장한다.

    기존에 같은 run_id로 저장된 결과가 있으면 먼저 지우고 다시 저장한다
    (완전성 비교는 같은 run에 대해 여러 번 다시 실행할 수 있기 때문).
    """
    session.execute(delete(CompletenessResult).where(CompletenessResult.run_id == run_id))
    objects = [CompletenessResult(run_id=run_id, **row) for row in rows]
    session.add_all(objects)
    session.commit()
    return objects


def get_completeness_results(session: Session, run_id: int) -> list[CompletenessResult]:
    stmt = select(CompletenessResult).where(CompletenessResult.run_id == run_id)
    return list(session.scalars(stmt))


# ---------------------------------------------------------------------------
# performance_logs (Phase 8)
# ---------------------------------------------------------------------------


def add_performance_log(session: Session, run_id: int, **counts_and_seconds) -> PerformanceLog:
    """대용량 처리 성능 측정값을 저장한다. 실제로 측정한 값만 넘겨야 한다.

    counts_and_seconds: total_rows, fast_path_count, alias_count, fuzzy_count,
    embedding_count, context_rerank_count, manual_review_count, unresolved_count,
    cache_hit_count, processing_seconds.
    """
    log = PerformanceLog(run_id=run_id, **counts_and_seconds)
    session.add(log)
    session.commit()
    session.refresh(log)
    return log


def list_performance_logs(session: Session, limit: int = 20) -> list[PerformanceLog]:
    stmt = select(PerformanceLog).order_by(PerformanceLog.created_at.desc()).limit(limit)
    return list(session.scalars(stmt))
