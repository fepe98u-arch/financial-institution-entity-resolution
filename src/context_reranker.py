"""문맥 기반 재평가 (Context Reranking).

실제 Cross-Encoder 모델은 쓰지 않는다 — 계획서 21번 섹션이 허용하는 Fallback
방식으로, Embedding Top-1 후보에 대해 문맥(context_text)에 금융 관련 키워드
(institution_master.keywords)나 혼동 방지 키워드(institution_master.negative_keywords)
가 있는지를 규칙으로 확인한다.

가중합 점수 대신 조건(규칙)으로 판단하는 이유: "왜 자동 확정했는지"를
숨김없이 설명할 수 있어야 하기 때문이다 (계획서 30번 섹션 설명가능성).

실측 근거: 이 Embedding 모델은 "농협"과 "NH농협은행"의 유사도를 0.909로,
"OO농협"과는 0.868로 계산한다 — 두 값이 매우 가까워서 점수만으로는 안전하게
구분할 수 없다. 그래서 규칙은 다음과 같다:

1. 혼동 방지 키워드가 문맥에 하나라도 있으면 → 절대 자동 확정하지 않는다.
2. 혼동 방지 키워드가 없고, 금융 키워드가 1개 이상 있고, Embedding 유사도가
   embedding_floor 이상이면 → 자동 확정한다.
3. 그 외(문맥 근거가 없는 경우)에는 → 검토 필요로 남긴다.

embedding_floor는 공식 감사기준이 아니라 config/model_config.yaml에서
조정 가능한 기본값이다.
"""

from dataclasses import dataclass

DEFAULT_EMBEDDING_FLOOR = 0.85


def _matched_keywords(context_text: str, keywords_csv: str | None) -> list[str]:
    if not keywords_csv or not context_text:
        return []
    keywords = [k.strip() for k in keywords_csv.split(",") if k.strip()]
    return [k for k in keywords if k in context_text]


def negative_keyword_hits(context_text: str | None, institution) -> list[str]:
    """문맥에 이 기관의 혼동 방지 키워드가 있는지 확인한다.

    FAST PATH의 Fuzzy 자동 확정처럼 문맥을 보지 않고 내려진 판단에도 이
    안전장치를 적용한다 — 예: "농협"은 짧아서 "NH농협" 별칭과 rapidfuzz
    유사도 90점이 나와 자동 확정될 수 있는데, 문맥이 "농산물 구매"라면
    막아야 한다.
    """
    return _matched_keywords(context_text or "", institution.negative_keywords)


@dataclass
class RerankDecision:
    confirmed: bool
    positive_keywords: list[str]
    negative_keywords: list[str]
    reason: str


def evaluate_candidate(
    context_text: str | None, institution, embedding_score: float, embedding_floor: float = DEFAULT_EMBEDDING_FLOOR
) -> RerankDecision:
    """Embedding Top-1 후보 하나를 문맥과 함께 재평가한다."""
    context_text = context_text or ""

    negative_hits = _matched_keywords(context_text, institution.negative_keywords)
    if negative_hits:
        return RerankDecision(
            confirmed=False,
            positive_keywords=[],
            negative_keywords=negative_hits,
            reason=f"혼동 방지 키워드 {negative_hits} 포함 → 자동 확정 거부",
        )

    positive_hits = _matched_keywords(context_text, institution.keywords)
    if positive_hits and embedding_score >= embedding_floor:
        return RerankDecision(
            confirmed=True,
            positive_keywords=positive_hits,
            negative_keywords=[],
            reason=(
                f"Embedding {embedding_score:.3f} >= threshold {embedding_floor:.2f} 이고 "
                f"금융 키워드 {positive_hits} 포함 → 자동 정규화"
            ),
        )

    return RerankDecision(
        confirmed=False,
        positive_keywords=positive_hits,
        negative_keywords=[],
        reason=(
            f"Embedding {embedding_score:.3f}, 금융 키워드 {positive_hits or '없음'} — "
            "자동 확정 조건(키워드 근거 + threshold)을 충족하지 못해 검토 필요"
        ),
    )
