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
from src.synthetic_data_generator import generate_synthetic_journal

settings = load_settings()

st.set_page_config(page_title=settings["app"]["title"], layout="wide")

if "journal_df" not in st.session_state:
    st.session_state.journal_df = None
if "column_mapping" not in st.session_state:
    st.session_state.column_mapping = {}

PAGES_IMPLEMENTED = ["Dashboard", "분개장 업로드", "컬럼 Mapping"]
PAGES_PLANNED = [
    "금융기관 정규화 (Phase 3~5)",
    "AI 결과 (Phase 4~5)",
    "Human Review (Phase 5~6)",
    "금융기관 Master (Phase 2)",
    "Alias Master (Phase 2~3)",
    "회사 금융기관 목록 (Phase 7)",
    "완전성 비교 (Phase 7)",
    "모델 성능 (Phase 8)",
    "처리 성능 (Phase 8)",
    "Feedback (Phase 6)",
    "Database 상태 (Phase 2)",
    "설정 (Phase 2+)",
]

st.sidebar.title(settings["app"]["title"])
page = st.sidebar.radio("메뉴", PAGES_IMPLEMENTED + PAGES_PLANNED)
st.sidebar.markdown("---")
st.sidebar.caption("현재는 Phase 1만 구현되어 있습니다. 그 외 메뉴는 자리 표시일 뿐 동작하지 않습니다.")


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


if page == "Dashboard":
    page_dashboard()
elif page == "분개장 업로드":
    page_upload()
elif page == "컬럼 Mapping":
    page_column_mapping()
else:
    st.title(page)
    st.info("이 메뉴는 아직 구현되지 않았습니다. 계획서의 개발 순서(Phase)에 따라 이후에 추가됩니다.")
