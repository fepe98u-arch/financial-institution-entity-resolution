"""Phase 4 (Embedding/AI PATH) 테스트.

sentence-transformers 모델을 실제로 로딩해서 검증한다. 최초 실행 시 모델을
다운로드해야 하므로(약 470MB, 1회) 인터넷이 없거나 다운로드에 실패하면 이
테스트들은 실패가 아니라 건너뜀(skip) 처리된다.
"""

import pytest

from src.database.models import InstitutionAlias, InstitutionMaster

try:
    from src.embedding_service import encode_texts

    encode_texts(["연결 확인용 텍스트"])
    _EMBEDDING_AVAILABLE = True
    _EMBEDDING_ERROR = None
except Exception as e:  # 모델 다운로드 실패, 인터넷 없음 등
    _EMBEDDING_AVAILABLE = False
    _EMBEDDING_ERROR = str(e)

pytestmark = pytest.mark.skipif(
    not _EMBEDDING_AVAILABLE,
    reason=f"Embedding 모델을 사용할 수 없어 건너뜁니다: {_EMBEDDING_ERROR}",
)


def _make_institution(institution_id: int, canonical_name: str, aliases: list[str]) -> InstitutionMaster:
    institution = InstitutionMaster(institution_id=institution_id, canonical_name=canonical_name, active=True)
    institution.aliases = [InstitutionAlias(alias_text=text, alias_type="ALIAS", active=True) for text in aliases]
    return institution


def _institutions():
    return [
        _make_institution(1, "NH농협은행", ["농협은행", "농은", "NH농협"]),
        _make_institution(2, "KB국민은행", ["국민은행", "KB국민"]),
        _make_institution(3, "신한은행", ["신한", "신한 BIZ"]),
    ]


def test_encode_texts_returns_one_vector_per_input():
    embeddings = encode_texts(["농협은행", "국민은행", "신한은행"])
    assert embeddings.shape[0] == 3


def test_build_alias_embedding_index_covers_all_active_aliases():
    from src.candidate_retriever import build_alias_embedding_index

    texts, owners, embeddings = build_alias_embedding_index(_institutions())
    # 표준명 3개 + 별칭 3+2+2개 = 10개
    assert len(texts) == 10
    assert len(owners) == 10
    assert embeddings.shape[0] == 10


def test_find_embedding_candidates_ranks_exact_alias_highest():
    from src.candidate_retriever import build_alias_embedding_index, find_embedding_candidates

    texts, owners, embeddings = build_alias_embedding_index(_institutions())
    results = find_embedding_candidates(["농은"], texts, owners, embeddings, limit=2)

    top1 = results["농은"][0]
    assert top1.canonical_name == "NH농협은행"
    assert top1.score > 0.9  # 완전히 같은 텍스트("농은")이므로 거의 1.0에 가까움


def test_embedding_does_not_auto_confirm_hard_negative_examples():
    """실측: 'OO농협'은 Embedding 단독으로 NH농협은행과 높은 유사도가 나올 수 있다.

    문맥 재평가가 없는 상태에서는 위험하므로, 파이프라인이 이를 절대
    review_status='AUTO'로 만들지 않는지 확인한다 (apply_embedding_path 검증).
    """
    from src.normalization_pipeline import apply_embedding_path, resolve_vendor_expressions

    institutions = _institutions()
    texts = ["OO농협", "농협유통", "NH투자"]
    resolved = resolve_vendor_expressions(texts, institutions, fuzzy_auto_threshold=90.0)
    for text in texts:
        assert resolved[text]["normalization_method"] == "UNRESOLVED"

    updated, error = apply_embedding_path(resolved, institutions)
    assert error is None
    for text in texts:
        # Embedding이 후보를 찾아 method가 EMBEDDING으로 바뀌더라도, review_status는
        # 절대 AUTO가 아니어야 한다 (자동 확정 금지).
        assert updated[text]["review_status"] == "NEEDS_REVIEW", text
