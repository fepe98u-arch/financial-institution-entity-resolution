"""PostgreSQL 연결/CRUD 테스트.

이 프로젝트는 SQLite를 쓰지 않기로 했으므로, 테스트도 실제 PostgreSQL에
접속해서 검증한다. DATABASE_URL이 없거나 서버에 연결할 수 없으면 이 테스트들은
'실패'가 아니라 '건너뜀(skip)'으로 처리한다 — PostgreSQL이 없다고 해서
자동으로 다른 DB를 대신 쓰지 않기 때문이다.
"""

import pytest
from sqlalchemy import delete, select

from src.database.connection import check_connection, get_engine, get_session
from src.database.models import InstitutionAlias, InstitutionMaster
from src.database.repository import (
    add_alias,
    add_institution,
    get_db_counts,
    init_db,
    list_aliases,
    list_institutions,
    set_institution_active,
)

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
    # repository 함수들은 즉시 commit하므로, rollback이 아니라 명시적으로
    # 테스트가 만든 데이터(이름이 '_pytest'로 끝나는 것)를 지운다.
    test_institution_ids = session.scalars(
        select(InstitutionMaster.institution_id).where(InstitutionMaster.canonical_name.like("%_pytest"))
    ).all()
    if test_institution_ids:
        session.execute(delete(InstitutionAlias).where(InstitutionAlias.institution_id.in_(test_institution_ids)))
        session.execute(delete(InstitutionMaster).where(InstitutionMaster.institution_id.in_(test_institution_ids)))
        session.commit()
    session.close()


def test_add_and_list_institution(db_session):
    institution = add_institution(db_session, "테스트은행_pytest", "BANK")
    names = [i.canonical_name for i in list_institutions(db_session)]
    assert "테스트은행_pytest" in names
    set_institution_active(db_session, institution.institution_id, False)


def test_add_alias(db_session):
    institution = add_institution(db_session, "테스트은행_alias_pytest", "BANK")
    add_alias(db_session, institution.institution_id, "테스트은행약칭")
    aliases = [a.alias_text for a in list_aliases(db_session, institution.institution_id)]
    assert "테스트은행약칭" in aliases


def test_get_db_counts_returns_numbers(db_session):
    counts = get_db_counts(db_session)
    assert isinstance(counts["institution_count"], int)
    assert isinstance(counts["alias_count"], int)
