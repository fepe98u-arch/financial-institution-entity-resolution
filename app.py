"""Streamlit 진입점.

Phase 1 범위: 분개장 업로드, 샘플 데이터 생성, 컬럼 매핑, context_text 미리보기.
그 외 사이드바 메뉴는 이후 Phase에서 구현되는 자리 표시(placeholder)이다.
"""

from pathlib import Path

import streamlit as st

from src.column_mapper import (
    CONTEXT_FIELDS,
    FIELD_LABELS,
    REQUIRED_FIELDS,
    build_context_text,
    validate_mapping,
)
from src.config_loader import load_settings
from src.data_loader import load_journal_file
from src.database.connection import check_connection, get_engine, get_session
from src.database.repository import (
    add_alias,
    add_institution,
    get_db_counts,
    init_db,
    list_aliases,
    list_institutions,
    seed_sample_master_data,
    set_alias_active,
    set_institution_active,
)
from src.synthetic_data_generator import generate_synthetic_journal

INSTITUTION_TYPES = ["BANK", "SECURITIES", "INSURANCE", "OTHER"]

settings = load_settings()

st.set_page_config(page_title=settings["app"]["title"], layout="wide")

if "journal_df" not in st.session_state:
    st.session_state.journal_df = None
if "column_mapping" not in st.session_state:
    st.session_state.column_mapping = {}

PAGES_IMPLEMENTED = [
    "Dashboard",
    "분개장 업로드",
    "컬럼 Mapping",
    "금융기관 Master",
    "Alias Master",
    "Database 상태",
]
PAGES_PLANNED = [
    "금융기관 정규화 (Phase 3~5)",
    "AI 결과 (Phase 4~5)",
    "Human Review (Phase 5~6)",
    "회사 금융기관 목록 (Phase 7)",
    "완전성 비교 (Phase 7)",
    "모델 성능 (Phase 8)",
    "처리 성능 (Phase 8)",
    "Feedback (Phase 6)",
    "설정 (Phase 2+)",
]

st.sidebar.title(settings["app"]["title"])
page = st.sidebar.radio("메뉴", PAGES_IMPLEMENTED + PAGES_PLANNED)
st.sidebar.markdown("---")
st.sidebar.caption("현재는 Phase 1~2만 구현되어 있습니다. 그 외 메뉴는 자리 표시일 뿐 동작하지 않습니다.")


def page_dashboard():
    st.title("Dashboard")
    df = st.session_state.journal_df
    if df is None:
        st.info("아직 불러온 분개장이 없습니다. '분개장 업로드' 메뉴에서 파일을 올리거나 샘플 데이터를 생성하세요.")
        return

    col1, col2 = st.columns(2)
    col1.metric("총 분개 수", f"{df.height:,}")
    col2.metric("컬럼 수", df.width)
    st.caption(
        "금융기관 탐지 수, FAST PATH/AI PATH 처리 건수 등은 Phase 3 이후 구현됩니다. "
        "지금은 실제로 계산되지 않으므로 표시하지 않습니다."
    )


def page_upload():
    st.title("분개장 업로드")
    tab_upload, tab_sample = st.tabs(["파일 업로드", "샘플 데이터 생성"])

    with tab_upload:
        uploaded = st.file_uploader("CSV 또는 Excel(xlsx) 파일", type=settings["file_upload"]["allowed_extensions"])
        if uploaded is not None:
            try:
                df = load_journal_file(uploaded)
            except Exception as e:
                st.error(f"파일을 읽는 중 오류가 발생했습니다: {e}")
            else:
                st.session_state.journal_df = df
                st.session_state.column_mapping = {}
                st.success(f"{uploaded.name} 로드 완료 ({df.height:,}행 x {df.width}열)")

    with tab_sample:
        st.caption("실제 데이터가 없을 때 기능을 테스트해볼 수 있는 가상 샘플입니다 (실제 고객 데이터 아님).")
        n_rows = st.number_input(
            "생성할 행 수",
            min_value=10,
            max_value=50000,
            value=settings["synthetic_data"]["default_rows"],
            step=10,
        )
        if st.button("샘플 분개 생성"):
            df = generate_synthetic_journal(n_rows=int(n_rows))
            st.session_state.journal_df = df
            st.session_state.column_mapping = {}
            out_dir = Path("data/synthetic")
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / "sample_journal.csv"
            df.write_csv(out_path)
            st.success(f"샘플 {df.height:,}행 생성 완료. {out_path} 에 저장했습니다.")

    df = st.session_state.journal_df
    if df is not None:
        st.subheader("미리보기")
        st.dataframe(df.head(settings["app"]["max_preview_rows"]), use_container_width=True)


def page_column_mapping():
    st.title("컬럼 Mapping")
    df = st.session_state.journal_df
    if df is None:
        st.info("먼저 '분개장 업로드' 메뉴에서 데이터를 불러오세요.")
        return

    st.caption("회사마다 분개장 컬럼명이 다르므로 직접 매핑합니다. '*' 표시는 필수 항목입니다.")

    columns = df.columns
    options = ["(선택 안 함)"] + columns
    mapping = {}
    for field, label in FIELD_LABELS.items():
        required = field in REQUIRED_FIELDS
        selected = st.selectbox(f"{label}{' *' if required else ''}", options, key=f"map_{field}")
        mapping[field] = None if selected == "(선택 안 함)" else selected

    st.session_state.column_mapping = mapping

    errors = validate_mapping(mapping)
    if errors:
        st.warning(" / ".join(errors))
        return

    if st.button("context_text 생성 및 미리보기"):
        try:
            result_df = build_context_text(df, mapping)
        except Exception as e:
            st.error(str(e))
        else:
            st.session_state.journal_df = result_df
            st.success("context_text 컬럼을 생성했습니다. (거래처 | 적요 | 계정과목 | 상대계정 순서로 결합)")
            preview_cols = [mapping[f] for f in CONTEXT_FIELDS if mapping.get(f)] + ["context_text"]
            st.dataframe(
                result_df.select(preview_cols).head(settings["app"]["max_preview_rows"]),
                use_container_width=True,
            )


def _show_db_connection_banner() -> bool:
    """연결 상태를 화면에 보여준다. 연결돼 있으면 True를 반환한다."""
    connected, message = check_connection()
    if not connected:
        st.warning(f"PostgreSQL 연결이 필요합니다.\n\n{message}\n\nREADME.md의 'PostgreSQL 연결 방법'을 참고하세요.")
        return False
    return True


def page_institution_master():
    st.title("금융기관 Master")
    if not _show_db_connection_banner():
        return

    session = get_session()
    try:
        init_db(get_engine())

        if st.button("샘플 마스터 데이터 추가 (NH농협은행/KB국민은행/신한은행 예시)"):
            added = seed_sample_master_data(session)
            st.success(f"{added}개 기관을 추가했습니다. (이미 있는 기관은 건너뜀)")

        institutions = list_institutions(session)
        st.subheader(f"등록된 금융기관 ({len(institutions)}개)")
        if institutions:
            st.dataframe(
                [
                    {
                        "institution_id": i.institution_id,
                        "canonical_name": i.canonical_name,
                        "institution_type": i.institution_type,
                        "english_name": i.english_name,
                        "active": i.active,
                    }
                    for i in institutions
                ],
                use_container_width=True,
            )
        else:
            st.info("등록된 금융기관이 없습니다. 위 버튼으로 샘플을 추가하거나 아래에서 직접 추가하세요.")

        st.subheader("금융기관 추가")
        with st.form("add_institution_form"):
            canonical_name = st.text_input("표준 명칭 (필수)")
            institution_type = st.selectbox("유형", INSTITUTION_TYPES)
            english_name = st.text_input("영문명 (선택)")
            keywords = st.text_input("금융 관련 키워드, 쉼표로 구분 (선택)")
            negative_keywords = st.text_input("혼동 방지 키워드, 쉼표로 구분 (선택)")
            submitted = st.form_submit_button("추가")
            if submitted:
                if not canonical_name.strip():
                    st.error("표준 명칭은 필수입니다.")
                else:
                    add_institution(
                        session,
                        canonical_name=canonical_name.strip(),
                        institution_type=institution_type,
                        english_name=english_name.strip() or None,
                        keywords=keywords.strip() or None,
                        negative_keywords=negative_keywords.strip() or None,
                    )
                    st.success(f"'{canonical_name}'을 추가했습니다.")

        if institutions:
            st.subheader("활성/비활성 전환")
            options = {f"{i.canonical_name} (id={i.institution_id}, active={i.active})": i for i in institutions}
            selected_label = st.selectbox("기관 선택", list(options.keys()), key="toggle_institution_select")
            target = options[selected_label]
            if st.button("활성/비활성 전환하기"):
                set_institution_active(session, target.institution_id, not target.active)
                st.success(f"'{target.canonical_name}'을 active={not target.active}로 변경했습니다.")
    except Exception as e:
        st.error(f"처리 중 오류가 발생했습니다: {e}")
    finally:
        session.close()


def page_alias_master():
    st.title("Alias Master")
    if not _show_db_connection_banner():
        return

    session = get_session()
    try:
        init_db(get_engine())

        institutions = list_institutions(session)
        if not institutions:
            st.info("먼저 '금융기관 Master' 메뉴에서 금융기관을 추가하세요.")
            return

        options = {i.canonical_name: i for i in institutions}
        selected_name = st.selectbox("금융기관 선택", list(options.keys()))
        institution = options[selected_name]

        aliases = list_aliases(session, institution.institution_id)
        st.subheader(f"'{selected_name}'의 별칭 ({len(aliases)}개)")
        if aliases:
            st.dataframe(
                [
                    {
                        "alias_id": a.alias_id,
                        "alias_text": a.alias_text,
                        "alias_type": a.alias_type,
                        "active": a.active,
                    }
                    for a in aliases
                ],
                use_container_width=True,
            )
        else:
            st.info("등록된 별칭이 없습니다.")

        st.subheader("별칭 추가")
        with st.form("add_alias_form"):
            alias_text = st.text_input("별칭 (필수)")
            alias_type = st.selectbox("유형", ["ALIAS", "ABBREVIATION", "ENGLISH", "TYPO"])
            submitted = st.form_submit_button("추가")
            if submitted:
                if not alias_text.strip():
                    st.error("별칭은 필수입니다.")
                else:
                    add_alias(session, institution.institution_id, alias_text.strip(), alias_type=alias_type)
                    st.success(f"'{alias_text}'를 '{selected_name}'의 별칭으로 추가했습니다.")

        if aliases:
            st.subheader("활성/비활성 전환")
            alias_options = {f"{a.alias_text} (id={a.alias_id}, active={a.active})": a for a in aliases}
            selected_alias_label = st.selectbox("별칭 선택", list(alias_options.keys()), key="toggle_alias_select")
            target_alias = alias_options[selected_alias_label]
            if st.button("별칭 활성/비활성 전환하기"):
                set_alias_active(session, target_alias.alias_id, not target_alias.active)
                st.success(f"'{target_alias.alias_text}'를 active={not target_alias.active}로 변경했습니다.")
    except Exception as e:
        st.error(f"처리 중 오류가 발생했습니다: {e}")
    finally:
        session.close()


def page_database_status():
    st.title("Database 상태")
    connected, message = check_connection()

    if connected:
        st.success("Connected")
    else:
        st.error("Not Connected")
        st.caption(message)
        st.info("README.md의 'PostgreSQL 연결 방법'을 참고해서 .env의 DATABASE_URL을 설정하세요.")
        return

    session = get_session()
    try:
        counts = get_db_counts(session)
        col1, col2 = st.columns(2)
        col1.metric("등록된 금융기관 수", counts["institution_count"])
        col2.metric("등록된 별칭 수", counts["alias_count"])
        st.caption(
            "Processing Run / Human Review / Feedback Label 수는 해당 기능이 구현되는 "
            "Phase 3 이후부터 표시됩니다."
        )
    finally:
        session.close()


if page == "Dashboard":
    page_dashboard()
elif page == "분개장 업로드":
    page_upload()
elif page == "컬럼 Mapping":
    page_column_mapping()
elif page == "금융기관 Master":
    page_institution_master()
elif page == "Alias Master":
    page_alias_master()
elif page == "Database 상태":
    page_database_status()
else:
    st.title(page)
    st.info("이 메뉴는 아직 구현되지 않았습니다. 계획서의 개발 순서(Phase)에 따라 이후에 추가됩니다.")
