"""비밀번호 게이트(src/auth.py)가 실제 화면에서 동작하는지 확인한다.

이 앱은 로컬 웹 서버이므로 127.0.0.1로 막아놔도 같은 컴퓨터의 다른 사용자/
프로그램이 포트에 접속하면 열려버린다 — 최소한의 문턱으로 비밀번호 게이트를
추가했다. .env에 APP_PASSWORD가 없으면 화면 자체가 열리지 않는다.
"""

import os

from streamlit.testing.v1 import AppTest

import src.config_loader  # noqa: F401  (import 시 .env를 로딩한다 — 단독 실행에도 필요)

APP_TIMEOUT = 20
_APP_PASSWORD = os.getenv("APP_PASSWORD")


def test_sidebar_is_hidden_before_login():
    at = AppTest.from_file("app.py")
    at.run(timeout=APP_TIMEOUT)

    assert not at.exception
    assert len(at.text_input) > 0  # 비밀번호 입력창은 보여야 한다
    assert len(at.sidebar.radio) == 0  # 사이드바(메뉴)는 아직 보이면 안 된다


def test_wrong_password_shows_error_and_keeps_sidebar_hidden():
    at = AppTest.from_file("app.py")
    at.run(timeout=APP_TIMEOUT)

    at.text_input[0].set_value("definitely-wrong-password").run(timeout=APP_TIMEOUT)
    at.button[0].click().run(timeout=APP_TIMEOUT)

    assert not at.exception
    assert len(at.error) > 0
    assert len(at.sidebar.radio) == 0


def test_correct_password_unlocks_sidebar():
    if not _APP_PASSWORD:
        import pytest

        pytest.skip("APP_PASSWORD가 .env에 없어 건너뜁니다 (이 테스트를 실제 환경에서 확인하려면 설정하세요).")

    at = AppTest.from_file("app.py")
    at.run(timeout=APP_TIMEOUT)

    at.text_input[0].set_value(_APP_PASSWORD).run(timeout=APP_TIMEOUT)
    at.button[0].click().run(timeout=APP_TIMEOUT)

    assert not at.exception
    assert len(at.sidebar.radio) > 0
