# 금융기관명 정규화 및 완전성 검토 시스템

Context-Aware Financial Institution Entity Resolution

## 이 프로그램은 무엇을 하는가

회계감사에서 은행 등 금융기관에 조회서를 보낼 때, 빠뜨린 금융기관이 없는지
확인하는 작업을 지원하는 도구입니다.

문제는 회사의 총계정원장/분개장에 같은 은행이 여러 이름으로 적혀 있다는
점입니다. 예를 들어 다음은 모두 "NH농협은행"을 가리킬 수 있습니다.

- 농협은행, NH농협, 농은, Nonghyup Bank, NH Bank, 농협 강남, 농협(대출)

반대로 이름이 비슷해도 다른 뜻인 경우도 있습니다.

- "OO농협" + "농산물 구매대금 지급" → 지역 농협(구매처)일 수도 있어 은행이라고
  단정하면 안 됩니다.
- "NH투자" → "NH"라는 글자가 있어도 NH농협은행이 아닙니다 (NH투자증권).

이 프로그램은 거래처명뿐 아니라 적요/계정과목/상대계정 같은 **문맥**을 함께
보고, 금융기관 이름을 표준 이름으로 정리(정규화)합니다. 확신이 낮은 경우는
사람이 직접 확인하도록 화면에 보여줍니다.

**이 프로그램이 하지 않는 것**: "조회서를 보내야 할 금융기관을 자동으로
확정"하지 않습니다. 최종 판단은 항상 감사인이 합니다. 이 프로그램은 "빠뜨리기
쉬운 후보를 찾아 보여주는" 보조 도구입니다.

## 지금 실제로 되는 것 / 안 되는 것 (Phase 5 기준)

**실제로 구현되어 동작하는 기능**
- 분개장 CSV/Excel 파일 업로드, 컬럼 매핑, context_text 생성 (Phase 1)
- PostgreSQL 연결 + 금융기관 Master/Alias Master 관리 (Phase 2)
- **FAST PATH** (Exact Match → Alias Match → Fuzzy Match, Phase 3): 등록된
  표준명/별칭과 완전히 같으면 즉시 확정, rapidfuzz 유사도가 90점(기본값)
  이상이면 자동 확정. 고유 거래처 표현만 매칭 후 Polars join으로 전체 행에
  broadcast (300,000행 반복 없음).
- **AI PATH: Embedding 기반 후보 검색** (Phase 4): FAST PATH로 확정 못한
  표현만 다국어 임베딩 모델(`paraphrase-multilingual-MiniLM-L12-v2`, 로컬
  실행)로 후보를 찾음.
- **Context Reranking** (Phase 5, 신규): context_text가 있으면 Embedding
  후보를 문맥으로 재평가합니다. 규칙은 가중합 점수가 아니라 조건으로
  판단합니다 (왜 확정했는지 숨김없이 설명하기 위해):
  1. 문맥에 이 기관의 혼동 방지 키워드(예: "농산물","원재료","유통","증권")가
     하나라도 있으면 → **절대 자동 확정하지 않음** (거부권).
  2. 혼동 방지 키워드가 없고, 금융 키워드(예: "대출","이자","예금")가 있고,
     Embedding 유사도가 0.85(기본값) 이상이면 → 자동 확정.
  3. 그 외(근거 부족)에는 → 검토 필요로 남김.
  - **실제로 이 규칙으로 실측 검증**: 같은 거래처 "농협"이라도
    "운영자금 대출이자 지급" 문맥에서는 자동 확정되고, "농산물 구매대금
    지급" 문맥에서는 검토 필요로 남는 것을 테스트로 확인했습니다 — 계획서
    1번 섹션의 핵심 예시 그대로입니다.
- **중요한 버그를 실측으로 발견하고 수정함**: "농협"은 짧아서 rapidfuzz로도
  "NH농협" 별칭과 유사도 90점이 나와, **문맥과 무관하게 FAST PATH에서 먼저
  자동 확정**될 수 있었습니다 (Context Rerank는 UNRESOLVED된 것만 처리하므로
  개입할 기회가 없었음). 그래서 Fuzzy로 자동 확정된 결과에도 혼동 방지
  키워드 거부권을 별도로 적용하는 안전장치를 추가했습니다
  (`_apply_fuzzy_negative_keyword_veto`).
- **Human Review 화면**: 검토 필요 항목을 원문/문맥/추천 기관/Top1·Top2
  점수/판단 근거와 함께 보여주고, "승인 / 다른 기관으로 변경 / 금융기관
  아님 / 판단 보류" 중 하나를 선택해 반영할 수 있습니다.
- Dashboard에 정규화 방법별 건수(EXACT/ALIAS/FUZZY/EMBEDDING/CONTEXT_RERANK/
  HUMAN/UNRESOLVED), 자동 확정/검토 필요 건수를 실제 계산값으로 표시
- pytest 자동 테스트 53개 (아래 "테스트 실행 결과" 참고)

**아직 구현되지 않은 기능**
- Human Review에서 내린 판단을 PostgreSQL(human_reviews 테이블)에 저장하는
  기능 — 지금은 화면 세션에만 반영되고, 새로고침하면 사라집니다 (Phase 6)
- Feedback Label 축적, 향후 모델 개선용 데이터 저장 (Phase 6)
- 회사 제출 금융기관 목록과의 완전성 비교 (Phase 7)
- normalization_results/candidate_scores를 PostgreSQL에 저장하는 기능 (지금은
  화면에서만 보여주고 DB에 저장하지 않음)
- Cross-Encoder 재순위화 — Context Reranking은 실제 Cross-Encoder가 아니라
  키워드 규칙 기반 Fallback입니다 (계획서 21번 섹션이 허용하는 방식이며,
  이 README와 코드 모두에서 Cross-Encoder를 썼다고 주장하지 않습니다)
- 대용량(10만/30만 건) 성능 테스트, Excel 결과 다운로드
- 모델 성능(Accuracy/Precision/Recall, False Normalization Rate 등) 평가

이 문서 뒤쪽의 "다음 단계"에 Phase 6부터의 계획이 있습니다.

## 왜 이런 기술을 쓰는가 (비개발자용 설명)

- **Polars**: 엑셀 프로그램보다 훨씬 빠르게 대량의 표(수십만 행)를 처리하는
  라이브러리입니다. pandas라는 더 흔한 라이브러리도 있지만, 대용량 처리에서
  Polars가 더 빠르고 메모리를 덜 씁니다.
- **Streamlit**: 클릭 몇 번으로 웹 화면(업로드, 버튼, 표)을 만들 수 있는
  라이브러리입니다. 별도로 웹사이트를 만들지 않아도 브라우저에서 프로그램을
  쓸 수 있게 해줍니다.
- **PostgreSQL** (Phase 2부터): 금융기관 목록, 사람이 검토한 결과, 처리
  이력 등을 안전하게 저장하는 데이터베이스입니다. 원본 분개 30만 건 전체를
  넣는 것이 아니라, "판단 결과와 상태"를 저장하는 용도로 씁니다.
- **Embedding / AI 모델** (Phase 4부터): "농은"처럼 사전에 없는 표현이 나왔을
  때, 의미가 비슷한 표준 금융기관 이름을 찾아주는 데 씁니다. 외부 인터넷
  API가 아니라 내 컴퓨터에서 도는 모델(`sentence-transformers`)을 씁니다.
  즉 분개 데이터가 외부 서버로 전송되지 않습니다. 모델 파일(약 470MB)은
  최초 1회만 인터넷에서 받고, 이후에는 `C:\Users\<사용자>\.cache\huggingface`
  에 저장되어 오프라인으로 동작합니다.
- **rapidfuzz** (Phase 3부터): 오타나 지점명이 붙은 표현("농협은행
  부산지점")처럼, 완전히 같지는 않지만 비슷한 문자열을 찾는 데 씁니다.
  AI 모델 없이 문자열 유사도만 계산하므로 빠릅니다.

## 왜 모든 행에 AI를 돌리지 않는가

"NH농협은행"처럼 누가 봐도 명확한 표현이 3만 번 반복된다고 해서, 3만 번 AI
모델을 부르는 것은 느리고 낭비입니다. 그래서:

1. 먼저 정확히 일치하는지, 미리 등록된 별칭 목록에 있는지, 유사도가 아주
   높은지를 빠르게 확인합니다 (FAST PATH: Exact → Alias → Fuzzy, Phase 3).
   이 세 가지는 AI 모델을 부르지 않습니다.
2. 이 세 가지로도 확정하지 못한 표현만 AI(Embedding)로 넘깁니다 (AI PATH,
   Phase 4).
3. context_text가 있으면 문맥(적요/계정과목 등)의 키워드로 Embedding 후보를
   재평가합니다 (Context Reranking, Phase 5). 이 단계에서 확정된 것만
   review_status='AUTO'가 되고, 근거가 부족하면 검토 필요로 남습니다.
4. 고유한 (거래처, context_text) 조합마다 한 번씩만 매칭/임베딩합니다
   (300,000행을 반복하지 않음). "농협"처럼 같은 거래처명이라도 문맥이
   다르면 별도로 처리됩니다 — 이게 바로 "문맥에 따라 캐시 키를 다르게
   한다"는 계획서 28번 섹션의 내용입니다.

## 폴더 구조

```
app.py                          Streamlit 화면 진입점
config/settings.yaml            화면 기본값 설정 (샘플 행 수, 미리보기 행 수 등)
config/model_config.yaml        Fuzzy 매칭 threshold 등 (Phase 3부터)
data/synthetic/                 가상 샘플 데이터 (실제 고객 데이터 절대 넣지 않음)
data/cache/                     대용량 파일 캐시용 (Phase 8부터 사용, 아직 비어 있음)
outputs/                        분석 결과 내보내기 (Phase 8부터 사용)
src/                            실제 처리 로직 (데이터 읽기, 컬럼 매핑 등)
src/database/connection.py      PostgreSQL 연결 (DATABASE_URL만 사용, 코드에 비밀번호 없음)
src/database/models.py          테이블 정의 (SQLAlchemy)
src/database/repository.py      금융기관 Master/Alias CRUD 함수
src/alias_matcher.py            Exact/Alias 매칭 (Phase 3)
src/fuzzy_matcher.py            rapidfuzz 유사도 매칭 (Phase 3)
src/embedding_service.py        임베딩 모델 로딩/인코딩 (Phase 4)
src/candidate_retriever.py      Embedding 기반 후보 검색 (Phase 4)
src/context_reranker.py         문맥 기반 재평가 규칙 (Phase 5)
src/human_review.py             Human Review 판단 반영 (Phase 5, DB 저장은 Phase 6)
src/normalization_pipeline.py   FAST PATH + AI PATH + Context Rerank 파이프라인
tests/                          pytest 자동 테스트
```

## 실행 방법

1. 아래 명령으로 필요한 패키지가 설치된 가상환경을 만듭니다 (이미 만들어져
   있다면 건너뜁니다). torch는 CPU 전용 버전을 먼저 설치해야 용량이 훨씬
   작습니다 (안 하면 GPU용 CUDA 라이브러리까지 같이 받아져서 훨씬 큽니다).

   ```
   python -m venv .venv
   .venv\Scripts\pip install --index-url https://download.pytorch.org/whl/cpu torch
   .venv\Scripts\pip install -r requirements.txt
   ```

2. 화면을 실행합니다.

   ```
   .venv\Scripts\streamlit run app.py
   ```

3. 브라우저가 자동으로 열리며 `http://localhost:8501` 에서 화면을 볼 수
   있습니다.

4. 사이드바에서 순서대로 진행합니다:
   1. "금융기관 Master" → "샘플 마스터 데이터 추가" 버튼 (처음 한 번만)
   2. "분개장 업로드" → 파일을 올리거나 "샘플 데이터 생성" 버튼
   3. "컬럼 Mapping" → 거래처 등 컬럼 선택 → "context_text 생성"
   4. "금융기관 정규화" → (처음 한 번은 임베딩 모델 다운로드로 몇 분 걸릴 수
      있음) "정규화 실행" 버튼 → 결과 미리보기
   5. "Human Review" → 검토 필요 항목을 확인하고 승인/변경/보류 처리
   6. "Dashboard" → 방법별 처리 건수 확인

## 테스트 실행 방법 / 결과

```
.venv\Scripts\pytest -v
```

**실제로 실행한 결과 (2026-08-09 기준)**: 53개 전부 통과 (`53 passed`).

- DB 연결, FAST PATH(Exact/Alias/Fuzzy), Embedding, Context Reranking, Human
  Review까지 화면 흐름 전체(마스터 시딩 → 샘플 생성 → 컬럼 매핑 → 정규화
  실행 → Human Review 승인)를 실제 PostgreSQL + 실제 임베딩 모델로 확인.
- "OO농협"/"농협유통"/"NH투자"가 FAST PATH(rapidfuzz 45~60점), Embedding
  단독(문맥 없음), Context Rerank(문맥 있어도 혼동 방지 키워드 있음) 세
  경로 모두에서 절대 자동 확정되지 않는 것을 각각 실제 값으로 검증.
- **같은 거래처 "농협"이 문맥에 따라 다른 결과가 나오는 것을 실제로 확인**:
  "대출이자 지급" 문맥 → 자동 확정(AUTO), "농산물 구매대금 지급" 문맥 →
  검토 필요(NEEDS_REVIEW). (`test_context_rerank_distinguishes_same_vendor_by_context`)
- FAST PATH의 Fuzzy 자동 확정에 대한 안전장치(혼동 방지 키워드 거부권)가
  실제로 동작하는지도 별도로 검증
  (`test_apply_normalization_with_context_column_end_to_end`).
- 임베딩 모델을 다운로드할 수 없는 환경에서는 이 테스트들이 실패가 아니라
  건너뜀(skip) 처리되도록 만들어뒀습니다 (PostgreSQL과 동일한 패턴).

아직 완전성 비교, Feedback 관련 테스트는 해당 기능이 구현되지 않아 존재하지
않습니다. 30만 행 대용량 테스트도 아직 실행하지 않았습니다 (Phase 8에서 진행).

## PostgreSQL 연결 방법

**PostgreSQL 17이 이 컴퓨터에 설치되어 실행 중입니다.** 처음에는 설치되어
있지 않아서(직접 확인: `psql` 명령, Windows 서비스, `C:\Program
Files\PostgreSQL`, Docker 전부 없었음), winget으로 설치를 진행했습니다
(사용자가 명시적으로 "자동 설치해줘"라고 요청해서 진행한 것이며, 기본적으로
이 프로그램은 PostgreSQL을 자동으로 설치하지 않습니다).

실제로 진행한 절차:
1. `winget install PostgreSQL.PostgreSQL.17` (무인 설치 모드)로 서버 설치
2. `postgresql-x64-17` 서비스가 실행 중인지 확인 (`sc query`)
3. `psql`로 데이터베이스(`financial_entity_resolution`)와 앱 전용 계정
   (`app_user`) 생성 — 관리자(superuser) 계정과 앱 계정 비밀번호는 각각
   무작위로 생성해서 화면에 노출하지 않았습니다
4. `.env`에 `DATABASE_URL` 설정 (실제 비밀번호가 들어있으므로 `.env`는
   git에 올라가지 않습니다 — `.gitignore` 확인)
5. `check_connection()`으로 `Connected` 확인, pytest로 실제 CRUD 테스트

**다른 컴퓨터에서 이 프로젝트를 새로 실행할 때** PostgreSQL이 없다면 아래를
직접 진행해야 합니다 (자동 설치를 원치 않으면 이 절차를 그대로 따르세요):

1. https://www.postgresql.org/download/windows/ 에서 설치 프로그램을 받아
   설치합니다.
2. SQL Shell(psql)에서 데이터베이스 생성:
   ```sql
   CREATE DATABASE financial_entity_resolution;
   ```
3. 앱 전용 계정 생성:
   ```sql
   CREATE USER app_user WITH PASSWORD '원하는_비밀번호';
   GRANT ALL PRIVILEGES ON DATABASE financial_entity_resolution TO app_user;
   ```
4. `.env` 파일(`.env.example`을 복사)에 `DATABASE_URL` 설정:
   ```
   DATABASE_URL=postgresql+psycopg://app_user:원하는_비밀번호@localhost:5432/financial_entity_resolution
   ```
5. Streamlit의 "Database 상태" 메뉴 또는 `pytest tests/test_database.py -v`로
   연결 확인.

연결에 실패하면 화면과 테스트 모두 "PostgreSQL 연결이 필요합니다"라고
표시합니다 (자동으로 다른 DB로 대체하지 않습니다).

## 기본 SQL 예제

Streamlit 화면 뒤에서 실제로는 이런 SQL이 실행됩니다 (SQLAlchemy가
값을 안전하게 바인딩하므로, 사용자 입력을 문자열로 이어붙여 SQL을 만들지
않습니다).

등록된 금융기관 전체 조회:
```sql
SELECT institution_id, canonical_name, institution_type
FROM institution_master
WHERE active = TRUE;
```

특정 금융기관의 별칭 조회:
```sql
SELECT alias_id, alias_text, alias_type
FROM institution_alias
WHERE institution_id = :institution_id;
```

아래 두 쿼리는 `normalization_results`/`human_reviews`에 실제 데이터가
쌓이면 쓸 수 있는 예시입니다 (정규화/Human Review 결과는 아직 이 테이블에
저장하지 않고 화면에서만 보여주므로, 지금은 테이블이 비어 있습니다 —
저장 기능은 Phase 6에서 추가할 계획입니다):

```sql
-- 수동 검토가 필요한 건 조회
SELECT * FROM normalization_results WHERE review_status = 'NEEDS_REVIEW';

-- 사용자가 AI 추천을 다른 기관으로 바꾼 사례 조회
SELECT * FROM human_reviews WHERE review_action = 'CHANGE_INSTITUTION';
```

## 보안 관련 주의사항

- 실제 회사 분개 데이터는 `data/synthetic/`(가상 샘플 폴더)에 절대 넣지
  않습니다.
- 업로드한 원본 파일은 프로그램이 수정하지 않습니다. 결과는 항상 새 파일/새
  컬럼으로 추가됩니다.
- DB 접속 정보(비밀번호 등)는 `.env` 파일에만 두고, 코드에 직접 적지
  않습니다. `.env`는 git에 올라가지 않습니다 (`.gitignore` 확인).
- 외부 LLM API(OpenAI, Claude API 등)를 호출하지 않습니다. AI 기능은 모두
  내 컴퓨터에서 실행되는 모델을 사용할 계획입니다.

## 다음 단계 (계획서 기준 Phase 6~9)

- ~~Phase 2: PostgreSQL 연결, 금융기관 Master/별칭 테이블~~ (완료)
- ~~Phase 3: 정확 일치, 별칭 매칭, 유사도(rapidfuzz) 매칭~~ (완료)
- ~~Phase 4: Embedding 모델, 후보 검색~~ (완료)
- ~~Phase 5: 문맥 기반 재평가(Context Reranking), Human Review 화면~~ (완료.
  Cross-Encoder가 아닌 키워드 규칙 기반 Fallback이며, 이 점을 코드/README에
  명시함. Human Review는 화면 반영까지만 되고 DB 저장은 Phase 6)
- Phase 6: Human Review 결과 PostgreSQL 저장, Feedback 데이터 축적
- Phase 7: 회사 제출 금융기관 목록 업로드, 완전성 비교(누락 후보 도출)
- Phase 8: 성능 평가, 대용량(30만 건) 테스트, Excel 결과 다운로드
- Phase 9: pytest 보강, README 최종화

각 Phase가 끝나면 실제로 무엇이 되고 무엇이 안 되는지 이 README와 함께
보고합니다.
