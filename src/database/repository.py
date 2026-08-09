"""institution_master / institution_alias에 대한 기본 CRUD 함수.

모든 조회는 SQLAlchemy ORM을 통해 이루어지며, 문자열을 이어붙여 SQL을
직접 만들지 않는다 (SQL Injection 방지). 원본 300,000건 분개 저장용이 아니라
마스터 데이터와 실행 상태 관리용 DB이다.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.database.models import Base, InstitutionAlias, InstitutionMaster


def init_db(engine) -> None:
    """정의된 모든 테이블을 생성한다 (이미 있으면 건너뜀)."""
    Base.metadata.create_all(engine)


# ---------------------------------------------------------------------------
# institution_master
# ---------------------------------------------------------------------------


def add_institution(
    session: Session,
    canonical_name: str,
    institution_type: str,
    english_name: str | None = None,
    keywords: str | None = None,
    negative_keywords: str | None = None,
) -> InstitutionMaster:
    institution = InstitutionMaster(
        canonical_name=canonical_name,
        institution_type=institution_type,
        english_name=english_name,
        keywords=keywords,
        negative_keywords=negative_keywords,
        active=True,
    )
    session.add(institution)
    session.commit()
    session.refresh(institution)
    return institution


def list_institutions(session: Session, active_only: bool = False) -> list[InstitutionMaster]:
    stmt = select(InstitutionMaster).order_by(InstitutionMaster.canonical_name)
    if active_only:
        stmt = stmt.where(InstitutionMaster.active.is_(True))
    return list(session.scalars(stmt))


def set_institution_active(session: Session, institution_id: int, active: bool) -> None:
    institution = session.get(InstitutionMaster, institution_id)
    if institution is None:
        raise ValueError(f"institution_id={institution_id} 를 찾을 수 없습니다.")
    institution.active = active
    session.commit()


# ---------------------------------------------------------------------------
# institution_alias
# ---------------------------------------------------------------------------


def add_alias(
    session: Session,
    institution_id: int,
    alias_text: str,
    alias_type: str | None = None,
) -> InstitutionAlias:
    alias = InstitutionAlias(
        institution_id=institution_id,
        alias_text=alias_text,
        normalized_alias=alias_text.strip().upper(),
        alias_type=alias_type,
        active=True,
    )
    session.add(alias)
    session.commit()
    session.refresh(alias)
    return alias


def list_aliases(session: Session, institution_id: int | None = None) -> list[InstitutionAlias]:
    stmt = select(InstitutionAlias).order_by(InstitutionAlias.alias_text)
    if institution_id is not None:
        stmt = stmt.where(InstitutionAlias.institution_id == institution_id)
    return list(session.scalars(stmt))


def set_alias_active(session: Session, alias_id: int, active: bool) -> None:
    alias = session.get(InstitutionAlias, alias_id)
    if alias is None:
        raise ValueError(f"alias_id={alias_id} 를 찾을 수 없습니다.")
    alias.active = active
    session.commit()


# ---------------------------------------------------------------------------
# 상태 조회 (Database 상태 화면에서 사용)
# ---------------------------------------------------------------------------


def get_db_counts(session: Session) -> dict:
    """비밀번호 등 민감정보 없이, 화면에 보여줄 개수만 반환한다."""
    return {
        "institution_count": session.scalar(select(func.count()).select_from(InstitutionMaster)) or 0,
        "alias_count": session.scalar(select(func.count()).select_from(InstitutionAlias)) or 0,
    }


# ---------------------------------------------------------------------------
# 샘플 마스터 데이터 (완전한 목록이 아닌, 시작용 제한된 예시)
# ---------------------------------------------------------------------------

_SAMPLE_INSTITUTIONS = [
    {
        "canonical_name": "NH농협은행",
        "institution_type": "BANK",
        "english_name": "Nonghyup Bank",
        "keywords": "대출,차입,이자,예금,계좌,송금",
        "negative_keywords": "농산물,원재료,조합원,유통,증권",
        "aliases": ["농협은행", "NH농협", "농은", "NH Bank", "농협 강남", "농협(대출)"],
    },
    {
        "canonical_name": "KB국민은행",
        "institution_type": "BANK",
        "english_name": "KB Kookmin Bank",
        "keywords": "대출,차입,이자,예금,계좌,송금",
        "negative_keywords": None,
        "aliases": ["국민은행", "KB국민", "KB BANK", "케이비국민"],
    },
    {
        "canonical_name": "신한은행",
        "institution_type": "BANK",
        "english_name": "Shinhan Bank",
        "keywords": "대출,차입,이자,예금,계좌,송금",
        "negative_keywords": None,
        "aliases": ["신한", "신한 BIZ"],
    },
]


def seed_sample_master_data(session: Session) -> int:
    """샘플 금융기관/별칭을 추가한다. 이미 있는 canonical_name은 건너뛴다(중복 방지).

    Returns: 새로 추가된 기관 수.
    """
    existing_names = {i.canonical_name for i in list_institutions(session)}
    added = 0
    for item in _SAMPLE_INSTITUTIONS:
        if item["canonical_name"] in existing_names:
            continue
        institution = add_institution(
            session,
            canonical_name=item["canonical_name"],
            institution_type=item["institution_type"],
            english_name=item["english_name"],
            keywords=item["keywords"],
            negative_keywords=item["negative_keywords"],
        )
        for alias_text in item["aliases"]:
            add_alias(session, institution.institution_id, alias_text, alias_type="ALIAS")
        added += 1
    return added
