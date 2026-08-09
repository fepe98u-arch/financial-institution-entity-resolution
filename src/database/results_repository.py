"""정규화 실행 이력(processing_runs), 분석 결과(normalization_results),
Human Review(human_reviews), Feedback Label(feedback_labels)에 대한 저장/조회 함수.

institution_master/institution_alias는 repository.py에서, 실행 결과와 사람의
판단은 이 파일에서 다룬다 (역할 분리).

지금은 ORM 객체를 하나씩 만들어 session.add_all()로 저장한다 — 수백~수천 건
수준에서는 충분히 빠르지만, 30만 행 전체를 이 방식으로 저장하는 것은 아직
성능 검증을 하지 않았다 (Phase 8 대용량 테스트에서 확인할 부분).
"""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.database.models import FeedbackLabel, HumanReview, NormalizationResult, ProcessingRun

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


def save_normalization_results(session: Session, run_id: int, rows: list[dict]) -> list[NormalizationResult]:
    """정규화 결과를 run_id에 연결해서 한 번에 저장한다.

    rows의 각 dict는 NormalizationResult 컬럼명과 일치하는 키를 가져야 한다
    (run_id는 이 함수가 채운다).
    """
    objects = [NormalizationResult(run_id=run_id, **row) for row in rows]
    session.add_all(objects)
    session.commit()
    return objects


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
