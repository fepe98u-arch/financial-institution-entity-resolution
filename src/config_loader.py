import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def load_settings() -> dict:
    settings_path = BASE_DIR / "config" / "settings.yaml"
    with open(settings_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_fuzzy_auto_threshold() -> float:
    return float(load_model_config()["fuzzy_matching"]["auto_threshold"])


def get_context_rerank_embedding_floor() -> float:
    return float(load_model_config()["context_rerank"]["embedding_floor"])


def load_model_config() -> dict:
    """FAST PATH/AI PATH 매칭 threshold 등 모델 관련 설정을 읽는다. (Phase 3부터 사용)"""
    config_path = BASE_DIR / "config" / "model_config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_database_url() -> str | None:
    """PostgreSQL 접속 정보는 .env의 DATABASE_URL에서만 읽는다. (Phase 2부터 사용)"""
    return os.getenv("DATABASE_URL")
