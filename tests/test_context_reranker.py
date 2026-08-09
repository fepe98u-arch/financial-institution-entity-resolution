from src.context_reranker import evaluate_candidate
from src.database.models import InstitutionMaster

FLOOR = 0.85


def _nh_institution() -> InstitutionMaster:
    return InstitutionMaster(
        institution_id=1,
        canonical_name="NH농협은행",
        keywords="대출,차입,이자,예금,계좌,송금",
        negative_keywords="농산물,원재료,조합원,유통,증권",
    )


def test_negative_keyword_always_blocks_auto_confirm_even_with_high_score():
    institution = _nh_institution()
    decision = evaluate_candidate("OO농협 | 농산물 구매대금 지급 | 원재료 | 외상매입금", institution, embedding_score=0.99)
    assert decision.confirmed is False
    assert "농산물" in decision.negative_keywords


def test_positive_keyword_with_high_score_confirms():
    institution = _nh_institution()
    decision = evaluate_candidate(
        "농협 | 운영자금 대출이자 지급 | 이자비용 | 장기차입금", institution, embedding_score=0.91, embedding_floor=FLOOR
    )
    assert decision.confirmed is True
    assert set(decision.positive_keywords) & {"대출", "차입", "이자"}


def test_no_context_evidence_stays_needs_review():
    """긍정도 부정도 없는 문맥은, 점수가 높아도 자동 확정하지 않는다 (증거 없으면 검토).

    주의: '보통예금'처럼 흔한 상대계정에는 '예금' 키워드가 포함되어 있어 이미
    긍정 신호로 잡힌다 (이는 실제로 타당하다 — 계좌 관련 거래라는 뜻이므로).
    그래서 여기서는 키워드와 전혀 겹치지 않는 계정(소모품비/미지급금)을 쓴다.
    """
    institution = _nh_institution()
    decision = evaluate_candidate("농협 | 비품 구매대금 지급 | 소모품비 | 미지급금", institution, embedding_score=0.909, embedding_floor=FLOOR)
    assert decision.confirmed is False


def test_positive_keyword_but_score_below_floor_stays_needs_review():
    institution = _nh_institution()
    decision = evaluate_candidate(
        "농협 | 대출이자 지급 | 이자비용 | 장기차입금", institution, embedding_score=0.5, embedding_floor=FLOOR
    )
    assert decision.confirmed is False


def test_empty_context_text_never_confirms():
    institution = _nh_institution()
    decision = evaluate_candidate(None, institution, embedding_score=0.99, embedding_floor=FLOOR)
    assert decision.confirmed is False
