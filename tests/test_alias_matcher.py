from src.alias_matcher import build_lookup_table, match_exact_or_alias, normalize_for_matching
from src.database.models import InstitutionAlias, InstitutionMaster


def _make_institution(institution_id: int, canonical_name: str, aliases: list[str]) -> InstitutionMaster:
    institution = InstitutionMaster(institution_id=institution_id, canonical_name=canonical_name, active=True)
    institution.aliases = [
        InstitutionAlias(alias_text=text, alias_type="ALIAS", active=True) for text in aliases
    ]
    return institution


def test_normalize_for_matching_removes_spaces_and_uppercases():
    assert normalize_for_matching("NH 농협은행") == "NH농협은행"
    assert normalize_for_matching("kb bank") == "KBBANK"


def test_exact_match_on_canonical_name():
    institutions = [_make_institution(1, "NH농협은행", ["농협은행", "NH농협"])]
    lookup = build_lookup_table(institutions)
    result = match_exact_or_alias("NH농협은행", lookup)
    assert result is not None
    assert result.match_source == "CANONICAL"
    assert result.canonical_name == "NH농협은행"


def test_alias_match():
    institutions = [_make_institution(1, "NH농협은행", ["농협은행", "농은"])]
    lookup = build_lookup_table(institutions)
    result = match_exact_or_alias("농은", lookup)
    assert result is not None
    assert result.canonical_name == "NH농협은행"


def test_no_match_returns_none():
    institutions = [_make_institution(1, "NH농협은행", ["농협은행"])]
    lookup = build_lookup_table(institutions)
    assert match_exact_or_alias("테스트전자", lookup) is None


def test_inactive_institution_excluded():
    institution = _make_institution(1, "NH농협은행", ["농협은행"])
    institution.active = False
    lookup = build_lookup_table([institution])
    assert match_exact_or_alias("NH농협은행", lookup) is None
