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


def _make_institution(
    institution_id: int,
    canonical_name: str,
    aliases: list[str],
    keywords: str | None = None,
    negative_keywords: str | None = None,
) -> InstitutionMaster:
    institution = InstitutionMaster(
        institution_id=institution_id,
        canonical_name=canonical_name,
        active=True,
        keywords=keywords,
        negative_keywords=negative_keywords,
    )
    institution.aliases = [InstitutionAlias(alias_text=text, alias_type="ALIAS", active=True) for text in aliases]
    return institution


def _institutions():
    return [
        _make_institution(
            1,
            "NH농협은행",
            ["농협은행", "농은", "NH농협"],
            keywords="대출,차입,이자,예금,계좌,송금",
            negative_keywords="농산물,원재료,조합원,유통,증권",
        ),
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


def test_embedding_without_context_never_auto_confirms():
    """context_text가 없으면(Phase 4와 동일한 상황) Embedding 결과는 항상 검토 필요다."""
    from src.normalization_pipeline import resolve_ai_path

    institutions = _institutions()
    texts = ["OO농협", "농협유통", "NH투자"]
    pairs = [(text, None) for text in texts]

    results = resolve_ai_path(pairs, institutions)
    for text in texts:
        assert results[(text, None)]["review_status"] == "NEEDS_REVIEW", text
        assert results[(text, None)]["normalization_method"] == "EMBEDDING"


def test_context_rerank_distinguishes_same_vendor_by_context():
    """계획서 1번 섹션의 핵심 예시: 같은 '농협'이라도 문맥에 따라 결과가 달라야 한다."""
    from src.normalization_pipeline import resolve_ai_path

    institutions = _institutions()
    pairs = [
        ("농협", "농협 | 운영자금 대출이자 지급 | 이자비용 | 장기차입금"),  # 은행 거래 문맥
        ("농협", "농협 | 농산물 구매대금 지급 | 원재료 | 외상매입금"),  # 구매처 문맥
    ]
    results = resolve_ai_path(pairs, institutions)

    bank_context_result = results[pairs[0]]
    purchase_context_result = results[pairs[1]]

    assert bank_context_result["review_status"] == "AUTO", bank_context_result["reason"]
    assert bank_context_result["canonical_institution"] == "NH농협은행"

    assert purchase_context_result["review_status"] == "NEEDS_REVIEW", purchase_context_result["reason"]


def test_context_rerank_negative_keyword_blocks_negative_examples():
    from src.normalization_pipeline import resolve_ai_path

    institutions = _institutions()
    pairs = [
        ("OO농협", "OO농협 | 농산물 구매대금 지급 | 원재료 | 외상매입금"),
        ("농협유통", "농협유통 | 상품 매입대금 지급 | 상품 | 외상매입금"),
        ("NH투자", "NH투자 | 증권 매매 정산 | 단기매매증권 | 보통예금"),
    ]
    results = resolve_ai_path(pairs, institutions)
    for pair in pairs:
        assert results[pair]["review_status"] == "NEEDS_REVIEW", (pair, results[pair]["reason"])
