"""유사도(rapidfuzz) 기반 매칭 (FAST PATH 3단계).

오타, 띄어쓰기 차이 등으로 정확 일치/별칭 일치에 실패한 표현을 대상으로
Master/Alias 전체와의 유사도를 계산해 Top-N 후보를 찾는다.
점수는 실제 rapidfuzz 계산값만 사용하며, 임의로 점수를 만들어내지 않는다.
"""

from dataclasses import dataclass

from rapidfuzz import fuzz, process

from src.alias_matcher import InstitutionLookupEntry, normalize_for_matching


@dataclass
class FuzzyCandidate:
    institution_id: int
    canonical_name: str
    matched_text: str
    score: float  # rapidfuzz.fuzz.WRatio 기준 0~100


def find_fuzzy_candidates(
    vendor_text: str, lookup: dict[str, InstitutionLookupEntry], limit: int = 2
) -> list[FuzzyCandidate]:
    """lookup에 등록된 모든 표준명/별칭과의 유사도 Top-N을 반환한다."""
    if not lookup:
        return []

    normalized_vendor = normalize_for_matching(vendor_text)
    choices = list(lookup.keys())
    matches = process.extract(normalized_vendor, choices, scorer=fuzz.WRatio, limit=limit)

    candidates = []
    for matched_key, score, _ in matches:
        entry = lookup[matched_key]
        candidates.append(FuzzyCandidate(entry.institution_id, entry.canonical_name, entry.match_text, score))
    return candidates
