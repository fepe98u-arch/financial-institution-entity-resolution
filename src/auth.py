"""아주 단순한 비밀번호 게이트.

정식 로그인 시스템이 아니다. 이 앱은 로컬 웹 서버로 뜨기 때문에, 127.0.0.1로
막아놔도 같은 컴퓨터의 다른 사용자 계정이나 다른 프로그램이 포트에 접속하면
그대로 열려버린다 — 회계 분개 데이터를 다루는 화면이라 최소한의 문턱이
필요해서 추가했다.

.env에 APP_PASSWORD가 없으면 화면을 아예 열지 않는다 (비밀번호가 없어도
동작하는 안전한 기본값을 두지 않는다).
"""

import os
import secrets

import streamlit as st


def require_password(app_title: str) -> bool:
    """비밀번호 확인 결과를 반환한다. 통과 전에는 로그인 화면만 그린다."""
    correct_password = os.getenv("APP_PASSWORD")
    if not correct_password:
        st.error(
            "APP_PASSWORD가 .env에 설정되어 있지 않아 화면을 열 수 없습니다. "
            ".env.example을 참고해서 APP_PASSWORD를 설정하세요."
        )
        return False

    if st.session_state.get("authenticated"):
        return True

    st.title(app_title)
    st.caption("회계 분개 데이터를 다루는 화면이라 비밀번호로 보호됩니다.")
    entered = st.text_input("비밀번호", type="password", key="password_input")
    if st.button("입장"):
        if secrets.compare_digest(entered, correct_password):
            st.session_state.authenticated = True
            return True  # 같은 실행에서 바로 통과시킨다 (st.rerun()은 불필요한 재실행을 만든다)
        st.error("비밀번호가 올바르지 않습니다.")
    return False
