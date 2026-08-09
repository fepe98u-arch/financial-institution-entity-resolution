from src.alias_matcher import build_lookup_table
from src.database.models import InstitutionAlias, InstitutionMaster
from src.fuzzy_matcher import find_fuzzy_candidates


def _make_institution(institution_id: int, canonical_name: str, aliases: list[str]) -> InstitutionMaster:
    institution = InstitutionMaster(institution_id=institution_id, canonical_name=canonical_name, active=True)
    institution.aliases = [
        InstitutionAlias(alias_text=text, alias_type="ALIAS", active=True) for text in aliases
    ]
    return institution


def _lookup():
    return build_lookup_table(
        [
            _make_institution(1, "NH농협은행", ["농협은행", "농은"]),
            _make_institution(2, "KB국민은행", ["국민은행"]),
        ]
    )


def test_branch_suffix_variant_reaches_auto_threshold():
    """'농협은행 부산지점'처럼 지점명이 붙은 경우는 실제로 90점 이상이 나온다."""
    candidates = find_fuzzy_candidates("농협은행 부산지점", _lookup(), limit=2)
    assert candidates
    assert candidates[0].canonical_name == "NH농협은행"
    assert candidates[0].score >= 90


def test_single_character_typo_ranks_correct_candidate_but_stays_below_threshold():
    """짧은 한글 단어의 한 글자 오타('은헹')는 실제로는 75점 정도로, 90점 threshold를 넘지 못한다.

    즉 이 표현은 FAST PATH에서 자동 확정되지 않고 NEEDS_REVIEW로 남는다 (안전한 방향).
    임의로 점수를 부풀리지 않고, 실제 rapidfuzz 계산값을 그대로 확인한다.
    """
    candidates = find_fuzzy_candidates("농협은헹", _lookup(), limit=2)
    assert candidates
    assert candidates[0].canonical_name == "NH농협은행"
    assert candidates[0].score < 90


def test_unrelated_vendor_gets_low_score():
    candidates = find_fuzzy_candidates("테스트전자", _lookup(), limit=2)
    assert candidates
    assert candidates[0].score < 90


def test_negative_examples_score_below_auto_threshold():
    """OO농협/농협유통/NH투자는 '농협'/'NH'라는 글자가 있어도 90점을 넘지 않아야 한다.

    실제로 감사업무에서 자동 정규화하면 안 되는 사례들 (계획서 1번 섹션 참고).
    """
    lookup = _lookup()
    for text in ["OO농협", "농협유통", "NH투자"]:
        candidates = find_fuzzy_candidates(text, lookup, limit=1)
        assert candidates[0].score < 90, f"{text} -> {candidates[0].canonical_name} ({candidates[0].score})"


def test_empty_lookup_returns_no_candidates():
    assert find_fuzzy_candidates("농협은행", {}, limit=2) == []
