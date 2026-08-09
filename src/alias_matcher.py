"""정확 일치 / 별칭 일치 매칭 (FAST PATH 1~2단계).

거래처 표현이 institution_master의 표준 명칭 또는 institution_alias의
별칭과 (공백/대소문자 차이만 있고) 완전히 같으면 바로 확정한다.
AI(Embedding)를 호출하지 않는 가장 빠른 경로이다.
"""

from dataclasses import dataclass


def normalize_for_matching(text: str) -> str:
    """공백을 전부 제거하고 영문을 대문자로 바꿔 비교 가능한 형태로 만든다."""
    return "".join(text.split()).upper()


@dataclass
class InstitutionLookupEntry:
    institution_id: int
    canonical_name: str
    match_text: str  # 실제로 일치한 표준명 또는 별칭 원문
    match_source: str  # "CANONICAL" 또는 alias_type (예: "ALIAS")


def build_lookup_table(institutions) -> dict[str, InstitutionLookupEntry]:
    """활성 상태인 institution_master + institution_alias로 조회 테이블을 만든다.

    institutions: InstitutionMaster 목록. 각 항목의 .aliases 관계가 이미
    로딩되어 있어야 한다 (repository.list_institutions_with_aliases 사용).
    같은 정규화 텍스트가 중복 등록되어 있으면 먼저 나온 것을 우선한다.
    """
    lookup: dict[str, InstitutionLookupEntry] = {}
    for institution in institutions:
        if not institution.active:
            continue
        canonical_key = normalize_for_matching(institution.canonical_name)
        lookup.setdefault(
            canonical_key,
            InstitutionLookupEntry(
                institution.institution_id, institution.canonical_name, institution.canonical_name, "CANONICAL"
            ),
        )
        for alias in institution.aliases:
            if not alias.active:
                continue
            alias_key = normalize_for_matching(alias.alias_text)
            lookup.setdefault(
                alias_key,
                InstitutionLookupEntry(
                    institution.institution_id,
                    institution.canonical_name,
                    alias.alias_text,
                    alias.alias_type or "ALIAS",
                ),
            )
    return lookup


def match_exact_or_alias(vendor_text: str, lookup: dict[str, InstitutionLookupEntry]) -> InstitutionLookupEntry | None:
    """정확 일치 또는 별칭 일치 결과를 반환한다. 없으면 None."""
    return lookup.get(normalize_for_matching(vendor_text))
