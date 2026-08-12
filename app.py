"""Streamlit 진입점.

Phase 1 범위: 분개장 업로드, 샘플 데이터 생성, 컬럼 매핑, context_text 미리보기.
그 외 사이드바 메뉴는 이후 Phase에서 구현되는 자리 표시(placeholder)이다.
"""

import time
from pathlib import Path

import polars as pl
import streamlit as st

from src.column_mapper import (
    CONTEXT_FIELDS,
    FIELD_LABELS,
    REQUIRED_FIELDS,
    build_context_text,
    validate_mapping,
)
from src.config_loader import get_context_rerank_embedding_floor, get_fuzzy_auto_threshold, load_settings
from src.data_loader import load_journal_file
from src.database.connection import check_connection, get_engine, get_session
from src.database.repository import (
    add_alias,
    add_institution,
    get_db_counts,
    init_db,
    list_aliases,
    list_institutions,
    list_institutions_with_aliases,
    seed_sample_master_data,
    set_alias_active,
    set_institution_active,
)
from src.database.results_repository import (
    add_feedback_label,
    add_human_review,
    add_performance_log,
    apply_review_to_results,
    complete_processing_run,
    count_feedback_labels,
    count_human_reviews,
    find_result_ids,
    list_processing_runs,
    save_completeness_results,
    save_normalization_results,
    start_processing_run,
)
from src.auth import require_password
from src.completeness_checker import (
    compare_completeness,
    get_institution_detail_rows,
    normalize_company_list,
    summarize_journal_by_institution,
)
from src.evaluation import compute_metrics, run_all_variants
from src.export_service import build_excel_report
from src.human_review import REVIEW_ACTIONS, apply_human_decision
from src.normalization_pipeline import apply_normalization, build_persistable_rows
from src.synthetic_data_generator import generate_synthetic_journal

INSTITUTION_TYPES = ["BANK", "SECURITIES", "INSURANCE", "OTHER"]

settings = load_settings()

st.set_page_config(page_title=settings["app"]["title"], layout="wide")

if not require_password(settings["app"]["title"]):
    st.stop()

if "journal_df" not in st.session_state:
    st.session_state.journal_df = None
if "column_mapping" not in st.session_state:
    st.session_state.column_mapping = {}
if "normalized_df" not in st.session_state:
    st.session_state.normalized_df = None
if "source_file_name" not in st.session_state:
    st.session_state.source_file_name = None
if "source_file_type" not in st.session_state:
    st.session_state.source_file_type = None
if "current_run_id" not in st.session_state:
    st.session_state.current_run_id = None
if "company_df" not in st.session_state:
    st.session_state.company_df = None
if "company_column" not in st.session_state:
    st.session_state.company_column = None
if "company_result_df" not in st.session_state:
    st.session_state.company_result_df = None
if "completeness_result" not in st.session_state:
    st.session_state.completeness_result = None
if "model_performance_results" not in st.session_state:
    st.session_state.model_performance_results = None
if "processing_performance_result" not in st.session_state:
    st.session_state.processing_performance_result = None

PAGES_IMPLEMENTED = [
    "Dashboard",
    "분개장 업로드",
    "컬럼 Mapping",
    "금융기관 정규화",
    "Human Review",
    "Feedback",
    "회사 금융기관 목록",
    "완전성 비교",
    "모델 성능",
    "처리 성능",
    "금융기관 Master",
    "Alias Master",
    "Database 상태",
]
PAGES_PLANNED = [
    "설정 (Phase 2+)",
]

st.sidebar.title(settings["app"]["title"])
page = st.sidebar.radio("메뉴", PAGES_IMPLEMENTED + PAGES_PLANNED)
st.sidebar.markdown("---")
st.sidebar.caption("현재는 Phase 1~8만 구현되어 있습니다. 그 외 메뉴는 자리 표시일 뿐 동작하지 않습니다.")


def page_dashboard():
    st.title("Dashboard")
    df = st.session_state.journal_df
    if df is None:
        st.info("아직 불러온 분개장이 없습니다. '분개장 업로드' 메뉴에서 파일을 올리거나 샘플 데이터를 생성하세요.")
        return

    col1, col2 = st.columns(2)
    col1.metric("총 분개 수", f"{df.height:,}")
    col2.metric("컬럼 수", df.width)

    result_df = st.session_state.normalized_df
    if result_df is None:
        st.caption("'금융기관 정규화' 메뉴에서 정규화를 실행하면 방법별 처리 건수가 여기에 표시됩니다.")
        return

    method_counts = result_df.group_by("normalization_method").len().sort("normalization_method")
    st.subheader("정규화 결과 (방법별 건수, 실제 계산값)")
    st.dataframe(method_counts, use_container_width=True)
    auto_count = result_df.filter(pl.col("review_status") == "AUTO").height
    needs_review_count = result_df.filter(pl.col("review_status") == "NEEDS_REVIEW").height
    col3, col4 = st.columns(2)
    col3.metric("자동 정규화(AUTO, FAST PATH만)", f"{auto_count:,}")
    col4.metric("검토 필요(NEEDS_REVIEW)", f"{needs_review_count:,}")
    st.caption(
        "CONTEXT_RERANK 방법으로 자동 확정(AUTO)된 건은 문맥의 금융 키워드까지 확인된 경우입니다. "
        "EMBEDDING 방법(context_text 없이 처리된 건)은 문맥 근거가 없어 항상 검토 필요로 남습니다."
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
                st.session_state.normalized_df = None
                st.session_state.current_run_id = None
                st.session_state.source_file_name = uploaded.name
                st.session_state.source_file_type = uploaded.name.rsplit(".", 1)[-1].lower()
                st.success(f"{uploaded.name} 로드 완료 ({df.height:,}행 x {df.width}열)")

    with tab_sample:
        st.caption("실제 데이터가 없을 때 기능을 테스트해볼 수 있는 가상 샘플입니다 (실제 고객 데이터 아님).")
        n_rows = st.number_input(
            "생성할 행 수",
            min_value=10,
            max_value=1_000_000,
            value=settings["synthetic_data"]["default_rows"],
            step=10,
        )
        if n_rows > 50_000:
            st.caption(
                "5만 행이 넘으면 정규화 실행 후 PostgreSQL 저장에 시간이 걸릴 수 있습니다 "
                "(실측: 100만 행 기준 약 42초, COPY 방식)."
            )
        if st.button("샘플 분개 생성"):
            df = generate_synthetic_journal(n_rows=int(n_rows))
            st.session_state.journal_df = df
            st.session_state.column_mapping = {}
            st.session_state.normalized_df = None
            st.session_state.current_run_id = None
            st.session_state.source_file_name = "synthetic_sample.csv"
            st.session_state.source_file_type = "synthetic"
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


def page_normalization():
    st.title("금융기관 정규화 (FAST PATH + Embedding + Context Rerank)")
    st.caption(
        "1) Exact Match → Alias Match → Fuzzy Match (FAST PATH) 순서로 시도합니다. "
        "2) 확정하지 못한 표현은 Embedding(AI PATH)으로 후보를 찾습니다. "
        "3) context_text가 있으면, 문맥의 금융 키워드/혼동 방지 키워드로 후보를 재평가합니다 "
        "(Context Reranking). 혼동 방지 키워드가 하나라도 있으면 — Fuzzy로 이미 자동 확정된 "
        "경우까지 포함해서 — 절대 자동 확정하지 않고 검토 필요로 되돌립니다."
    )

    df = st.session_state.journal_df
    mapping = st.session_state.column_mapping
    if df is None or not mapping.get("vendor"):
        st.info("먼저 '분개장 업로드'에서 데이터를 불러오고, '컬럼 Mapping'에서 거래처 컬럼을 지정하세요.")
        return

    if not _show_db_connection_banner():
        return

    vendor_column = mapping["vendor"]
    has_context = "context_text" in df.columns
    if not has_context:
        st.info(
            "context_text 컬럼이 없습니다 — '컬럼 Mapping'에서 먼저 생성하면 문맥 재평가(Context "
            "Reranking)까지 적용됩니다. 지금은 거래처 이름만으로 FAST PATH/Embedding을 실행합니다."
        )

    threshold = get_fuzzy_auto_threshold()
    embedding_floor = get_context_rerank_embedding_floor()
    use_embedding = st.checkbox("Embedding(AI PATH) 사용", value=True)
    st.caption(f"Fuzzy 자동 정규화 threshold: {threshold:.1f}점, Context Rerank embedding_floor: {embedding_floor:.2f} (config/model_config.yaml)")
    if use_embedding:
        st.caption(
            "최초 실행 시 임베딩 모델(약 470MB)을 다운로드합니다. 인터넷이 필요하며, "
            "이후에는 로컬에 캐시되어 오프라인으로 동작합니다."
        )

    if st.button("정규화 실행"):
        session = get_session()
        try:
            init_db(get_engine())
            institutions = list_institutions_with_aliases(session, active_only=True)
        finally:
            session.close()

        if not institutions:
            st.warning("등록된 금융기관이 없습니다. '금융기관 Master' 메뉴에서 먼저 등록하세요.")
            return

        started = time.perf_counter()
        with st.spinner("정규화 실행 중..."):
            result_df, embedding_error = apply_normalization(
                df,
                vendor_column,
                institutions,
                threshold,
                use_embedding=use_embedding,
                context_column="context_text" if has_context else None,
                embedding_floor=embedding_floor,
            )
        elapsed_seconds = time.perf_counter() - started
        st.session_state.normalized_df = result_df
        if embedding_error:
            st.warning(embedding_error)
        st.success(f"{result_df.height:,}행에 대해 정규화를 완료했습니다. ({elapsed_seconds:.2f}초)")

        institutions_by_id = {i.institution_id: i for i in institutions}
        persistable_rows = build_persistable_rows(
            result_df,
            institutions_by_id,
            voucher_column=mapping.get("voucher_no"),
            context_column="context_text" if has_context else None,
        )
        session = get_session()
        try:
            run = start_processing_run(
                session,
                file_name=st.session_state.source_file_name or "unknown",
                file_type=st.session_state.source_file_type or "unknown",
                total_rows=result_df.height,
            )
            save_normalization_results(session, run.run_id, persistable_rows)
            complete_processing_run(session, run.run_id, processing_seconds=elapsed_seconds)
            st.session_state.current_run_id = run.run_id
            st.caption(f"정규화 결과 {len(persistable_rows):,}행을 PostgreSQL(run_id={run.run_id})에 저장했습니다.")
        except Exception as e:
            st.warning(f"결과를 PostgreSQL에 저장하지 못했습니다 (화면 표시/Human Review는 계속 동작합니다): {e}")
        finally:
            session.close()

    result_df = st.session_state.normalized_df
    if result_df is not None:
        st.subheader("결과 미리보기")
        preview_cols = [
            "detected_expression",
            "canonical_institution",
            "normalization_method",
            "top1_score",
            "top2_candidate",
            "top2_score",
            "review_status",
            "reason",
        ]
        st.dataframe(
            result_df.select(preview_cols).unique().head(settings["app"]["max_preview_rows"]),
            use_container_width=True,
        )

        st.subheader("Excel 다운로드")
        institution_summary = (
            result_df.group_by("canonical_institution")
            .agg(pl.len().alias("건수"))
            .filter(pl.col("canonical_institution").is_not_null())
            .sort("건수", descending=True)
        )
        manual_review = result_df.filter(pl.col("review_status") == "NEEDS_REVIEW")
        excel_bytes = build_excel_report(
            {
                "Normalized_Journal": result_df,
                "Institution_Summary": institution_summary,
                "Manual_Review": manual_review,
            }
        )
        st.download_button(
            "정규화 결과 Excel 다운로드",
            data=excel_bytes,
            file_name="normalization_result.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


def page_human_review():
    st.title("Human Review")
    st.caption(
        "자동으로 확정되지 않은 항목을 사람이 직접 확인합니다. '정규화 실행'을 거친 결과라면 "
        "여기서 내린 판단이 PostgreSQL의 normalization_results/human_reviews/feedback_labels에 "
        "저장됩니다. (정규화를 다시 실행하지 않고 이 세션에서 직접 만든 결과라면 저장할 "
        "run_id가 없어 화면에만 반영됩니다.)"
    )

    result_df = st.session_state.normalized_df
    if result_df is None:
        st.info("먼저 '금융기관 정규화'에서 정규화를 실행하세요.")
        return

    has_context = "context_text" in result_df.columns
    key_cols = ["detected_expression"] + (["context_text"] if has_context else [])
    display_cols = key_cols + [
        "canonical_institution",
        "institution_id",
        "normalization_method",
        "top1_score",
        "top2_candidate",
        "top2_score",
        "reason",
    ]

    needs_review = result_df.filter(pl.col("review_status") == "NEEDS_REVIEW").select(display_cols).unique(subset=key_cols)
    st.write(f"검토 필요 항목: {needs_review.height}건 (고유 표현 기준)")

    if needs_review.height == 0:
        st.success("검토가 필요한 항목이 없습니다.")
        return

    session = get_session()
    try:
        institutions = list_institutions(session, active_only=True)
    finally:
        session.close()
    institution_options = {i.canonical_name: (i.institution_id, i.canonical_name) for i in institutions}

    max_rows_to_show = 30
    rows = needs_review.head(max_rows_to_show).to_dicts()
    if needs_review.height > max_rows_to_show:
        st.caption(f"상위 {max_rows_to_show}건만 표시합니다 (전체 {needs_review.height}건).")

    for i, row in enumerate(rows):
        label = f"{row['detected_expression']} → {row.get('canonical_institution') or '후보 없음'} (top1={row.get('top1_score')})"
        with st.expander(label):
            st.write("원문:", row["detected_expression"])
            if has_context:
                st.write("문맥:", row.get("context_text"))
            st.write("추천 기관:", row.get("canonical_institution"))
            st.write("Top1 Score:", row.get("top1_score"))
            st.write("Top2 후보:", row.get("top2_candidate"), " / Score:", row.get("top2_score"))
            st.write("방법:", row.get("normalization_method"))
            st.write("근거:", row.get("reason"))

            action_label = st.radio("처리", list(REVIEW_ACTIONS.keys()), key=f"review_action_{i}", horizontal=True)
            override_institution = None
            if action_label == "다른 금융기관으로 변경":
                selected_name = st.selectbox("변경할 기관", list(institution_options.keys()), key=f"review_override_{i}")
                override_institution = institution_options[selected_name]

            if st.button("적용", key=f"review_apply_{i}"):
                match_columns = {col: row[col] for col in key_cols}
                action = REVIEW_ACTIONS[action_label]

                model_prediction = row.get("canonical_institution")
                if action == "APPROVE":
                    new_canonical, new_institution_id = model_prediction, row.get("institution_id")
                    user_decision = model_prediction
                elif action == "CHANGE_INSTITUTION":
                    new_institution_id, new_canonical = override_institution
                    user_decision = new_canonical
                elif action == "NOT_FINANCIAL_INSTITUTION":
                    new_canonical, new_institution_id = None, None
                    user_decision = "NOT_FINANCIAL_INSTITUTION"
                else:  # HOLD
                    new_canonical, new_institution_id = model_prediction, row.get("institution_id")
                    user_decision = "HOLD"

                st.session_state.normalized_df = apply_human_decision(
                    st.session_state.normalized_df, match_columns, action, override_institution
                )

                run_id = st.session_state.current_run_id
                if run_id is None:
                    st.success("반영했습니다. (이번 실행은 PostgreSQL에 저장되지 않아 화면 세션에만 반영됨)")
                else:
                    session = get_session()
                    try:
                        result_ids = find_result_ids(
                            session, run_id, row["detected_expression"], row.get("context_text") if has_context else None
                        )
                        new_review_status = "AUTO" if action in ("APPROVE", "CHANGE_INSTITUTION") else action
                        apply_review_to_results(
                            session, result_ids, new_review_status, new_canonical, new_institution_id,
                            normalization_method="HUMAN",
                        )
                        review_id = None
                        for result_id in result_ids:
                            review = add_human_review(session, result_id, model_prediction, user_decision, action)
                            review_id = review.review_id
                        if review_id is not None:
                            add_feedback_label(
                                session,
                                original_expression=row["detected_expression"],
                                context_text=row.get("context_text") if has_context else None,
                                model_prediction=model_prediction,
                                confirmed_label=user_decision,
                                source_review_id=review_id,
                            )
                        st.success(f"반영했습니다. (PostgreSQL human_reviews/feedback_labels에 저장, {len(result_ids)}건)")
                    except Exception as e:
                        st.warning(f"화면에는 반영했지만 PostgreSQL 저장에는 실패했습니다: {e}")
                    finally:
                        session.close()


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

        runs = list_processing_runs(session, limit=1000)
        col3, col4, col5 = st.columns(3)
        col3.metric("Processing Run 수", len(runs))
        col4.metric("Human Review 수", count_human_reviews(session))
        col5.metric("Feedback Label 수", count_feedback_labels(session))

        if runs:
            st.subheader("최근 실행 이력 (최대 20개)")
            st.dataframe(
                [
                    {
                        "run_id": r.run_id,
                        "file_name": r.file_name,
                        "file_type": r.file_type,
                        "total_rows": r.total_rows,
                        "status": r.status,
                        "processing_seconds": float(r.processing_seconds) if r.processing_seconds else None,
                        "created_at": r.created_at,
                    }
                    for r in runs[:20]
                ],
                use_container_width=True,
            )
    finally:
        session.close()


def page_feedback():
    st.title("Feedback")
    st.caption(
        "Human Review에서 사용자가 확정한 라벨을 모아둔 목록입니다. 향후 모델 개선(재학습/평가)에 "
        "사용할 수 있는 데이터를 쌓아두는 것이 목적이며, 지금 버전에서 이 데이터로 모델을 자동으로 "
        "다시 학습시키는 기능은 없습니다 (계획서에서도 이 범위까지만 요구함)."
    )
    if not _show_db_connection_banner():
        return

    session = get_session()
    try:
        from sqlalchemy import select

        from src.database.models import FeedbackLabel

        labels = list(session.scalars(select(FeedbackLabel).order_by(FeedbackLabel.created_at.desc()).limit(200)))
    finally:
        session.close()

    st.write(f"누적된 Feedback Label: {len(labels)}건 (최대 200건 표시)")
    if labels:
        st.dataframe(
            [
                {
                    "label_id": l.label_id,
                    "original_expression": l.original_expression,
                    "context_text": l.context_text,
                    "model_prediction": l.model_prediction,
                    "confirmed_label": l.confirmed_label,
                    "source_review_id": l.source_review_id,
                    "created_at": l.created_at,
                }
                for l in labels
            ],
            use_container_width=True,
        )
    else:
        st.info("아직 쌓인 Feedback Label이 없습니다. Human Review에서 판단을 반영하면 여기에 쌓입니다.")


def page_company_list():
    st.title("회사 금융기관 목록")
    st.caption(
        "회사가 제출한 금융기관 목록을 업로드합니다. '완전성 비교'에서 분개장(정규화 결과)과 "
        "비교합니다. 이 목록도 분개장과 같은 정규화 파이프라인(FAST PATH + Embedding)으로 "
        "처리됩니다. 실제 고객 데이터는 샘플 폴더에 넣지 마세요."
    )

    uploaded = st.file_uploader(
        "CSV 또는 Excel(xlsx) 파일", type=settings["file_upload"]["allowed_extensions"], key="company_uploader"
    )
    if uploaded is not None:
        try:
            df = load_journal_file(uploaded)
        except Exception as e:
            st.error(f"파일을 읽는 중 오류가 발생했습니다: {e}")
        else:
            st.session_state.company_df = df
            st.session_state.company_column = None
            st.session_state.company_result_df = None
            st.session_state.completeness_result = None
            st.success(f"{uploaded.name} 로드 완료 ({df.height:,}행 x {df.width}열)")

    df = st.session_state.company_df
    if df is None:
        st.info("업로드할 파일이 없다면 테스트용 가상 목록을 만들 수 있습니다.")
        if st.button("샘플 회사 목록 생성 (NH농협은행/신한은행만 포함 — KB국민은행은 의도적으로 제외)"):
            sample_df = pl.DataFrame({"institution_name": ["NH농협은행", "신한은행"]})
            st.session_state.company_df = sample_df
            st.session_state.company_column = "institution_name"
            st.session_state.company_result_df = None
            st.session_state.completeness_result = None
            st.success("샘플 목록을 만들었습니다.")
        return

    st.subheader("미리보기")
    st.dataframe(df.head(settings["app"]["max_preview_rows"]), use_container_width=True)

    columns = df.columns
    default_index = columns.index(st.session_state.company_column) if st.session_state.company_column in columns else 0
    selected_column = st.selectbox("금융기관명이 들어있는 컬럼", columns, index=default_index)
    st.session_state.company_column = selected_column
    st.caption(f"'{selected_column}' 컬럼의 고유 값 {df[selected_column].n_unique()}개를 금융기관명으로 사용합니다.")


def page_completeness():
    st.title("완전성 비교")
    st.caption(
        "A = 회사 제출 금융기관 목록, B = 분개장에서 발견된 금융기관(review_status가 AUTO 또는 "
        "HUMAN인 것만). **B - A(회사 제출 목록에는 없지만 분개장에서 발견된 금융기관)**가 가장 "
        "중요한 결과입니다 — '누락 확정'이 아니라 '추가 검토 후보'입니다. 최종 판단은 감사인이 "
        "합니다."
    )

    journal_df = st.session_state.normalized_df
    company_df = st.session_state.company_df
    company_column = st.session_state.company_column

    if journal_df is None:
        st.info("먼저 '금융기관 정규화'에서 분개장 정규화를 실행하세요.")
        return
    if company_df is None or not company_column:
        st.info("먼저 '회사 금융기관 목록'에서 목록을 업로드하고 컬럼을 지정하세요.")
        return

    if not _show_db_connection_banner():
        return

    threshold = get_fuzzy_auto_threshold()
    embedding_floor = get_context_rerank_embedding_floor()
    amount_column = st.session_state.column_mapping.get("amount")

    if st.button("완전성 비교 실행"):
        session = get_session()
        try:
            init_db(get_engine())
            institutions = list_institutions_with_aliases(session, active_only=True)
        finally:
            session.close()

        if not institutions:
            st.warning("등록된 금융기관이 없습니다. '금융기관 Master' 메뉴에서 먼저 등록하세요.")
            return

        with st.spinner("회사 제출 목록을 정규화하는 중..."):
            company_result_df, embedding_error = normalize_company_list(
                company_df, company_column, institutions, threshold, embedding_floor
            )
        st.session_state.company_result_df = company_result_df
        if embedding_error:
            st.warning(embedding_error)

        result = compare_completeness(company_result_df, journal_df, company_column)
        st.session_state.completeness_result = result

        run_id = st.session_state.current_run_id
        if run_id is not None:
            name_to_institution = {i.canonical_name: i for i in institutions}
            all_names = sorted(set(result["both"]) | set(result["additional_candidates"]) | set(result["company_only"]))
            summary_df = summarize_journal_by_institution(journal_df, all_names, amount_column)
            summary_by_name = {r["canonical_institution"]: r for r in summary_df.to_dicts()}

            rows = []
            for name in all_names:
                institution = name_to_institution.get(name)
                summary = summary_by_name.get(name, {})
                if name in result["additional_candidates"]:
                    status = "ADDITIONAL_CANDIDATE"
                elif name in result["company_only"]:
                    status = "COMPANY_ONLY_NOT_FOUND"
                else:
                    status = "MATCHED"
                rows.append(
                    {
                        "institution_id": institution.institution_id if institution else None,
                        "canonical_name": name,
                        "company_list_exists": name in result["both"] or name in result["company_only"],
                        "journal_detected": name in result["both"] or name in result["additional_candidates"],
                        "journal_count": summary.get("journal_count", 0),
                        "total_amount": summary.get("total_amount"),
                        "review_status": status,
                    }
                )
            session = get_session()
            try:
                save_completeness_results(session, run_id, rows)
                st.caption(f"완전성 비교 결과 {len(rows)}건을 PostgreSQL(run_id={run_id})에 저장했습니다.")
            except Exception as e:
                st.warning(f"완전성 비교 결과를 PostgreSQL에 저장하지 못했습니다: {e}")
            finally:
                session.close()
        else:
            st.caption("먼저 '금융기관 정규화'를 실행해서 run_id를 만들면, 이 비교 결과도 PostgreSQL에 저장됩니다.")

    result = st.session_state.completeness_result
    if result is None:
        return

    col1, col2, col3 = st.columns(3)
    col1.metric("A ∩ B (양쪽 다 있음)", len(result["both"]))
    col2.metric("B - A (추가 검토 후보)", len(result["additional_candidates"]))
    col3.metric("A - B (회사 목록에만 있음)", len(result["company_only"]))

    if result["unidentified_in_company_list"]:
        st.warning(f"회사 제출 목록에서 자동으로 식별하지 못한 항목: {result['unidentified_in_company_list']}")

    st.subheader("추가 검토 후보 (B - A) — 가장 중요")
    if not result["additional_candidates"]:
        st.success("추가 검토 후보가 없습니다.")
    else:
        summary_df = summarize_journal_by_institution(journal_df, result["additional_candidates"], amount_column)
        st.dataframe(summary_df, use_container_width=True)

        detail_columns = [
            c
            for c in ["detected_expression", "context_text", "normalization_method", "top1_score", "review_status"]
            if c in journal_df.columns
        ]
        selected = st.selectbox("상세 분개 보기", result["additional_candidates"])
        if selected:
            detail = get_institution_detail_rows(journal_df, selected, detail_columns)
            st.dataframe(detail, use_container_width=True)

    st.subheader("A ∩ B (회사 목록에도 있고 분개장에서도 발견됨)")
    st.write(result["both"] or "없음")

    st.subheader("A - B (회사 목록에는 있으나 분개장에서 발견되지 않음)")
    st.write(result["company_only"] or "없음")

    st.subheader("Excel 다운로드")
    additional_df = summarize_journal_by_institution(journal_df, result["additional_candidates"], amount_column)
    excel_bytes = build_excel_report(
        {
            "Additional_Candidates": additional_df,
            "Matched_Both": pl.DataFrame({"canonical_institution": result["both"]}),
            "Company_Only": pl.DataFrame({"canonical_institution": result["company_only"]}),
        }
    )
    st.download_button(
        "완전성 비교 결과 Excel 다운로드",
        data=excel_bytes,
        file_name="completeness_result.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def page_model_performance():
    st.title("모델 성능")
    st.caption(
        "완전히 가상의 라벨링된 평가 데이터셋(26건, src/evaluation.py)으로 4가지 구성을 비교합니다. "
        "여기 나오는 수치는 이 가상 데이터셋에 대한 실제 계산값이며, 공식 성능 지표나 감사기준이 "
        "아닙니다. 실제 데이터에서는 다른 값이 나올 수 있습니다."
    )

    if not _show_db_connection_banner():
        return

    if st.button("성능 평가 실행"):
        session = get_session()
        try:
            init_db(get_engine())
            institutions = list_institutions_with_aliases(session, active_only=True)
        finally:
            session.close()

        if not institutions:
            st.warning("등록된 금융기관이 없습니다. '금융기관 Master' 메뉴에서 먼저 등록하세요.")
            return

        threshold = get_fuzzy_auto_threshold()
        embedding_floor = get_context_rerank_embedding_floor()
        with st.spinner("4가지 구성으로 평가 실행 중..."):
            results = run_all_variants(institutions, threshold, embedding_floor)
        st.session_state.model_performance_results = results

    results = st.session_state.get("model_performance_results")
    if not results:
        return

    rows = []
    for variant_name, metrics in results.items():
        row = {"variant": variant_name}
        row.update({k: v for k, v in metrics.items() if k != "embedding_error"})
        rows.append(row)
    st.dataframe(pl.DataFrame(rows), use_container_width=True)

    st.caption(
        "false_normalization_rate = 자동 확정(AUTO/HUMAN)한 것 중 실제로 잘못된 비율입니다. "
        "coverage가 높아도 false_normalization_rate가 높다면 위험한 구성입니다 — 이 프로젝트는 "
        "자동처리율보다 이 값을 낮추는 것을 더 중요하게 봅니다."
    )

    excel_bytes = build_excel_report({"Model_Performance": pl.DataFrame(rows)})
    st.download_button(
        "모델 성능 결과 Excel 다운로드",
        data=excel_bytes,
        file_name="model_performance.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def page_processing_performance():
    st.title("처리 성능")
    st.caption(
        "가상 샘플 데이터로 대용량 처리 시간을 실제로 측정합니다. 측정하지 못한 값은 표시하지 "
        "않습니다 — 임의의 수치를 만들어내지 않습니다."
    )

    if not _show_db_connection_banner():
        return

    n_rows = st.number_input("생성할 행 수", min_value=1000, max_value=1_000_000, value=10000, step=1000)
    use_embedding = st.checkbox("Embedding(AI PATH) 포함", value=True, key="perf_use_embedding")

    if st.button("대용량 처리 성능 테스트 실행"):
        session = get_session()
        try:
            init_db(get_engine())
            institutions = list_institutions_with_aliases(session, active_only=True)
        finally:
            session.close()

        if not institutions:
            st.warning("등록된 금융기관이 없습니다. '금융기관 Master' 메뉴에서 먼저 등록하세요.")
            return

        threshold = get_fuzzy_auto_threshold()
        embedding_floor = get_context_rerank_embedding_floor()

        t0 = time.perf_counter()
        with st.spinner(f"{n_rows:,}행 가상 데이터 생성 중..."):
            perf_df = generate_synthetic_journal(n_rows=int(n_rows))
        t1 = time.perf_counter()

        mapping = {"vendor": "거래처", "description": "적요", "account": "계정과목", "counter_account": "상대계정"}
        perf_df = build_context_text(perf_df, mapping)
        t2 = time.perf_counter()

        unique_pairs = perf_df.select(["거래처", "context_text"]).unique().height

        with st.spinner("정규화 실행 중... (Embedding 최초 실행 시 모델 다운로드로 시간이 걸릴 수 있음)"):
            result_df, embedding_error = apply_normalization(
                perf_df,
                "거래처",
                institutions,
                threshold,
                use_embedding=use_embedding,
                context_column="context_text",
                embedding_floor=embedding_floor,
            )
        t3 = time.perf_counter()

        method_counts = {r["normalization_method"]: r["len"] for r in result_df.group_by("normalization_method").len().to_dicts()}
        manual_review_count = result_df.filter(pl.col("review_status") == "NEEDS_REVIEW").height

        perf_result = {
            "n_rows": int(n_rows),
            "generation_seconds": t1 - t0,
            "context_text_seconds": t2 - t1,
            "normalization_seconds": t3 - t2,
            "total_seconds": t3 - t0,
            "unique_pairs": unique_pairs,
            "cache_hit_count": int(n_rows) - unique_pairs,
            "method_counts": method_counts,
            "manual_review_count": manual_review_count,
            "embedding_error": embedding_error,
        }
        st.session_state.processing_performance_result = perf_result

        session = get_session()
        try:
            run = start_processing_run(session, f"perf_test_{n_rows}rows.csv", "synthetic", int(n_rows))
            add_performance_log(
                session,
                run.run_id,
                total_rows=int(n_rows),
                fast_path_count=method_counts.get("EXACT", 0),
                alias_count=method_counts.get("ALIAS", 0),
                fuzzy_count=method_counts.get("FUZZY", 0),
                embedding_count=method_counts.get("EMBEDDING", 0),
                context_rerank_count=method_counts.get("CONTEXT_RERANK", 0),
                manual_review_count=manual_review_count,
                unresolved_count=method_counts.get("UNRESOLVED", 0),
                cache_hit_count=int(n_rows) - unique_pairs,
                processing_seconds=t3 - t2,
            )
            complete_processing_run(session, run.run_id, processing_seconds=t3 - t0)
            st.caption(f"처리 성능 로그를 PostgreSQL(run_id={run.run_id})에 저장했습니다.")
        except Exception as e:
            st.warning(f"처리 성능 로그를 PostgreSQL에 저장하지 못했습니다: {e}")
        finally:
            session.close()

    perf_result = st.session_state.get("processing_performance_result")
    if not perf_result:
        return

    if perf_result["embedding_error"]:
        st.warning(perf_result["embedding_error"])

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("행 수", f"{perf_result['n_rows']:,}")
    col2.metric("고유 (거래처,문맥) 조합", f"{perf_result['unique_pairs']:,}")
    col3.metric("Cache로 재사용된 행", f"{perf_result['cache_hit_count']:,}")
    col4.metric("검토 필요 건수", f"{perf_result['manual_review_count']:,}")

    col5, col6, col7, col8 = st.columns(4)
    col5.metric("샘플 생성 시간", f"{perf_result['generation_seconds']:.3f}초")
    col6.metric("context_text 생성 시간", f"{perf_result['context_text_seconds']:.3f}초")
    col7.metric("정규화 처리 시간", f"{perf_result['normalization_seconds']:.3f}초")
    col8.metric("전체 시간", f"{perf_result['total_seconds']:.3f}초")

    st.subheader("처리 방법별 건수 (실제 계산값)")
    st.dataframe(
        pl.DataFrame({"method": list(perf_result["method_counts"].keys()), "count": list(perf_result["method_counts"].values())}),
        use_container_width=True,
    )
    st.caption(
        "고유 (거래처, 문맥) 조합 수가 전체 행 수보다 훨씬 적다는 것은, 실제로 같은 표현을 "
        "반복해서 재계산하지 않고 있다는 뜻입니다 (Polars join으로 broadcast)."
    )


if page == "Dashboard":
    page_dashboard()
elif page == "분개장 업로드":
    page_upload()
elif page == "컬럼 Mapping":
    page_column_mapping()
elif page == "금융기관 정규화":
    page_normalization()
elif page == "Human Review":
    page_human_review()
elif page == "Feedback":
    page_feedback()
elif page == "회사 금융기관 목록":
    page_company_list()
elif page == "완전성 비교":
    page_completeness()
elif page == "모델 성능":
    page_model_performance()
elif page == "처리 성능":
    page_processing_performance()
elif page == "금융기관 Master":
    page_institution_master()
elif page == "Alias Master":
    page_alias_master()
elif page == "Database 상태":
    page_database_status()
else:
    st.title(page)
    st.info("이 메뉴는 아직 구현되지 않았습니다. 계획서의 개발 순서(Phase)에 따라 이후에 추가됩니다.")
