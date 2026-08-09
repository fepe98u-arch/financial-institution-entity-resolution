"""PostgreSQL 연결 관리.

DB 접속정보는 코드에 직접 적지 않고 .env의 DATABASE_URL 환경변수에서만 읽는다.
PostgreSQL을 자동으로 설치하거나 서버 설정을 바꾸는 동작은 하지 않는다.
연결이 안 되면 예외 대신 명확한 상태값을 돌려주는 check_connection()을 사용한다.
"""

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from src.config_loader import get_database_url

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def get_engine() -> Engine:
    """SQLAlchemy Engine을 생성(1회)하고 재사용한다."""
    global _engine
    if _engine is None:
        database_url = get_database_url()
        if not database_url:
            raise RuntimeError(
                "DATABASE_URL이 설정되어 있지 않습니다. .env 파일에 DATABASE_URL을 설정하세요 "
                "(예시는 .env.example 참고)."
            )
        _engine = create_engine(database_url, pool_pre_ping=True)
    return _engine


def get_session() -> Session:
    """새 DB 세션을 반환한다. 호출한 쪽에서 사용 후 session.close()를 해야 한다."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine())
    return _SessionLocal()


def check_connection() -> tuple[bool, str]:
    """PostgreSQL에 실제로 접속해본다.

    Returns:
        (연결 성공 여부, 사람이 읽을 수 있는 상태 메시지). 비밀번호 등 민감정보는
        메시지에 절대 포함하지 않는다.
    """
    try:
        engine = get_engine()
        with engine.connect():
            pass
    except RuntimeError as e:
        return False, str(e)
    except OperationalError:
        return False, "PostgreSQL 연결이 필요합니다. .env의 DATABASE_URL과 PostgreSQL 서버 실행 상태를 확인하세요."
    except SQLAlchemyError as e:
        return False, f"DB 연결 중 오류가 발생했습니다: {type(e).__name__}"
    return True, "Connected"
