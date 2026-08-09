"""Embedding 기반 후보 검색 (AI PATH).

FAST PATH(Exact/Alias/Fuzzy)로 확정하지 못한 표현에 대해서만 호출한다.
금융기관 Master의 표준명 + 별칭들을 각각 임베딩해두고, 가장 비슷한 것을 찾는다.

실측 결과에 대한 중요한 주의사항: 이 모델로 "OO농협"과 "NH농협은행"의 유사도를
계산하면 0.8점대가 나온다 (글자가 비슷해서). 이 모듈은 문맥(적요/계정과목 등)을
보지 않으므로, 이 점수만으로 자동 정규화를 확정하면 위험하다 — 그래서
normalization_pipeline.py는 이 결과를 항상 '검토 필요'로만 취급한다
(문맥 재평가는 Phase 5에서 구현).
"""

from dataclasses import dataclass

from src.embedding_service import encode_texts


@dataclass
class EmbeddingCandidate:
    institution_id: int
    canonical_name: str
    matched_text: str
    score: float  # cosine similarity (실제로는 대체로 0~1 사이 값)


def build_alias_embedding_index(institutions):
    """활성 기관의 표준명+별칭 텍스트를 모아 한 번에 배치로 임베딩한다.

    Returns:
        (texts, owners, embeddings). institutions가 비어있으면 (empty).
        texts[i]/owners[i]가 embeddings[i]에 대응한다.
    """
    texts: list[str] = []
    owners: list[tuple[int, str]] = []
    for institution in institutions:
        if not institution.active:
            continue
        texts.append(institution.canonical_name)
        owners.append((institution.institution_id, institution.canonical_name))
        for alias in institution.aliases:
            if not alias.active:
                continue
            texts.append(alias.alias_text)
            owners.append((institution.institution_id, institution.canonical_name))

    if not texts:
        return [], [], None

    embeddings = encode_texts(texts)
    return texts, owners, embeddings


def find_embedding_candidates(
    vendor_texts: list[str], texts: list[str], owners: list[tuple[int, str]], embeddings, limit: int = 2
) -> dict[str, list[EmbeddingCandidate]]:
    """vendor_texts 전체를 한 번에 배치로 임베딩하고, 각각의 기관별 최고 점수 Top-N을 찾는다."""
    if not texts or not vendor_texts:
        return {text: [] for text in vendor_texts}

    from sentence_transformers import util

    query_embeddings = encode_texts(vendor_texts)
    sims = util.cos_sim(query_embeddings, embeddings)

    results: dict[str, list[EmbeddingCandidate]] = {}
    for i, vendor_text in enumerate(vendor_texts):
        scored = sorted(
            ((owners[j], texts[j], float(sims[i][j])) for j in range(len(texts))),
            key=lambda item: -item[2],
        )
        candidates: list[EmbeddingCandidate] = []
        seen_institution_ids: set[int] = set()
        for (institution_id, canonical_name), matched_text, score in scored:
            if institution_id in seen_institution_ids:
                continue  # 같은 기관은 가장 점수가 높은 별칭 하나만 남긴다
            seen_institution_ids.add(institution_id)
            candidates.append(EmbeddingCandidate(institution_id, canonical_name, matched_text, score))
            if len(candidates) >= limit:
                break
        results[vendor_text] = candidates
    return results
