"""PostgreSQL 테이블 정의 (SQLAlchemy ORM 모델).

이 프로젝트는 원본 분개 300,000건 전체를 DB에 저장하지 않는다.
DB는 "금융기관 마스터 정보"와 "분석 실행 상태·결과·사람의 검토 기록"을 관리하는
역할을 한다. 원본 분개 자체는 Polars로 파일 기반 처리한다.

Phase 2에서는 institution_master / institution_alias만 실제로 사용한다.
나머지 테이블은 Phase 3 이후 각 기능이 구현될 때 채워진다 (스키마만 미리 정의).
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class InstitutionMaster(Base):
    """표준 금융기관 목록. (Phase 2에서 사용)"""

    __tablename__ = "institution_master"

    institution_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    canonical_name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    institution_type: Mapped[str] = mapped_column(String(50), nullable=False)
    english_name: Mapped[str | None] = mapped_column(String(200))
    keywords: Mapped[str | None] = mapped_column(Text)
    negative_keywords: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    aliases: Mapped[list["InstitutionAlias"]] = relationship(
        back_populates="institution", cascade="all, delete-orphan"
    )


class InstitutionAlias(Base):
    """금융기관 별칭 목록. (Phase 2에서 사용)"""

    __tablename__ = "institution_alias"

    alias_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institution_master.institution_id"), nullable=False)
    alias_text: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(200), nullable=False)
    alias_type: Mapped[str | None] = mapped_column(String(50))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    institution: Mapped["InstitutionMaster"] = relationship(back_populates="aliases")


class ProcessingRun(Base):
    """분개장 분석 1회 실행 이력. (Phase 3~4부터 사용)"""

    __tablename__ = "processing_runs"

    run_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    processing_seconds: Mapped[float | None] = mapped_column(Numeric(12, 3))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class NormalizationResult(Base):
    """분개별 금융기관 정규화 결과. (Phase 3~5부터 사용)"""

    __tablename__ = "normalization_results"

    result_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("processing_runs.run_id"), nullable=False)
    original_row_id: Mapped[str] = mapped_column(String(50), nullable=False)
    detected_expression: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_expression: Mapped[str | None] = mapped_column(String(200))
    canonical_institution: Mapped[str | None] = mapped_column(String(200))
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institution_master.institution_id"))
    institution_type: Mapped[str | None] = mapped_column(String(50))
    normalization_method: Mapped[str] = mapped_column(String(30), nullable=False)
    top1_score: Mapped[float | None] = mapped_column(Numeric(6, 4))
    top2_candidate: Mapped[str | None] = mapped_column(String(200))
    top2_score: Mapped[float | None] = mapped_column(Numeric(6, 4))
    score_margin: Mapped[float | None] = mapped_column(Numeric(6, 4))
    review_status: Mapped[str] = mapped_column(String(30), nullable=False, default="UNRESOLVED")
    context_text: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    user_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CandidateScore(Base):
    """Embedding/Reranking 후보 Top-K 점수. (Phase 4~5부터 사용)"""

    __tablename__ = "candidate_scores"

    candidate_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("normalization_results.result_id"), nullable=False)
    candidate_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institution_master.institution_id"))
    candidate_name: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding_score: Mapped[float | None] = mapped_column(Numeric(6, 4))
    rerank_score: Mapped[float | None] = mapped_column(Numeric(6, 4))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class HumanReview(Base):
    """사람이 검토한 결과. (Phase 5~6부터 사용)"""

    __tablename__ = "human_reviews"

    review_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("normalization_results.result_id"), nullable=False)
    model_prediction: Mapped[str | None] = mapped_column(String(200))
    user_decision: Mapped[str | None] = mapped_column(String(200))
    review_action: Mapped[str] = mapped_column(String(30), nullable=False)
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class FeedbackLabel(Base):
    """향후 모델 개선을 위한 확정 라벨 축적. (Phase 6부터 사용)"""

    __tablename__ = "feedback_labels"

    label_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    original_expression: Mapped[str] = mapped_column(String(200), nullable=False)
    context_text: Mapped[str | None] = mapped_column(Text)
    model_prediction: Mapped[str | None] = mapped_column(String(200))
    confirmed_label: Mapped[str] = mapped_column(String(200), nullable=False)
    source_review_id: Mapped[int | None] = mapped_column(ForeignKey("human_reviews.review_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CompletenessResult(Base):
    """회사 제출 금융기관 목록 대비 완전성 비교 결과. (Phase 7부터 사용)"""

    __tablename__ = "completeness_results"

    completeness_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("processing_runs.run_id"), nullable=False)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institution_master.institution_id"))
    canonical_name: Mapped[str] = mapped_column(String(200), nullable=False)
    company_list_exists: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    journal_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    journal_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_amount: Mapped[float | None] = mapped_column(Numeric(18, 2))
    review_status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PerformanceLog(Base):
    """실행별 처리 성능 지표. (Phase 8부터 사용)"""

    __tablename__ = "performance_logs"

    performance_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("processing_runs.run_id"), nullable=False)
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    fast_path_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    alias_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fuzzy_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedding_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    context_rerank_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    manual_review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unresolved_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processing_seconds: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ModelConfig(Base):
    """Embedding/Reranking 모델 설정 및 threshold. (Phase 4~5부터 사용)"""

    __tablename__ = "model_configs"

    config_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    embedding_model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    reranker_model_name: Mapped[str | None] = mapped_column(String(200))
    embedding_threshold: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    rerank_threshold: Mapped[float | None] = mapped_column(Numeric(6, 4))
    margin_threshold: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
