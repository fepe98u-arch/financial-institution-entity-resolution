"""다국어 문장 임베딩 모델 로딩 및 인코딩.

외부 LLM API를 호출하지 않는다. sentence-transformers로 로컬에 다운로드된
모델을 실행하며, 최초 1회 인터넷에서 받은 뒤에는 오프라인으로 추론한다.
GPU가 없다고 가정하고 CPU에서 동작하는 모델을 기본값으로 쓴다.
"""

from functools import lru_cache

# 한국어/영문 금융기관명을 함께 처리할 수 있는 다국어 모델. CPU에서도 실행 가능.
DEFAULT_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


@lru_cache(maxsize=1)
def _load_model(model_name: str):
    # sentence-transformers/torch는 무겁기 때문에 실제로 필요할 때만 import한다.
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


def get_model(model_name: str = DEFAULT_MODEL_NAME):
    """모델을 최초 1회만 로딩(및 필요시 다운로드)하고, 이후에는 캐시된 인스턴스를 재사용한다."""
    return _load_model(model_name)


def encode_texts(texts: list[str], model_name: str = DEFAULT_MODEL_NAME):
    """문장 목록을 한 번에 배치로 임베딩한다 (한 문장씩 반복 호출하지 않음)."""
    model = get_model(model_name)
    return model.encode(texts, convert_to_tensor=True)
