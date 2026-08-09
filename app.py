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
    apply_review_to_results,
    complete_processing_run,
    count_feedback_labels,
    count_human_reviews,
    find_result_ids,
    list_processing_runs,
    save_normalization_results,
    start_processing_run,
)
from src.human_review import REVIEW_ACTIONS, apply_human_decision
from src.normalization_pipeline import apply_normalization, build_persistable_rows
from src.synthetic_data_generator import generate_synthetic_journal

INSTITUTION_TYPES = ["BANK", "SECURITIES", "INSURANCE", "OTHER"]

settings = load_settings()

st.set_page_config(page_title=settings["app"]["title"], layout="wide")

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

PAGES_IMPLEMENTED = [
    "Dashboard",
    "분개장 업로드",
    "컬럼 Mapping",
    "금융기관 정규화",
    "Human Review",
    "Feedback",
    "금융기관 Master",
    "Alias Master",
    "Database 상태",
]
PAGES_PLANNED = [
    "회사 금융기관 목록 (Phase 7)",
    "완전성 비교 (Phase 7)",
    "모델 성능 (Phase 8)",
    "처리 성능 (Phase 8)",
    "설정 (Phase 2+)",
]

st.sidebar.title(settings["app"]["title"])
page = st.sidebar.radio("메뉴", PAGES_IMPLEMENTED + PAGES_PLANNED)
st.sidebar.markdown("---")
st.sidebar.caption("현재는 Phase 1~6만 구현되어 있습니다. 그 외 메뉴는 자리 표시일 뿐 동작하지 않습니다.")


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
            max_value=50000,
            value=settings["synthetic_data"]["default_rows"],
            step=10,
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
elif page == "금융기관 Master":
    page_institution_master()
elif page == "Alias Master":
    page_alias_master()
elif page == "Database 상태":
    page_database_status()
else:
    st.title(page)
    st.info("이 메뉴는 아직 구현되지 않았습니다. 계획서의 개발 순서(Phase)에 따라 이후에 추가됩니다.")
