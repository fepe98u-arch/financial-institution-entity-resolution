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

## 지금 실제로 되는 것 / 안 되는 것 (Phase 3 기준)

**실제로 구현되어 동작하는 기능**
- 분개장 CSV/Excel 파일 업로드 (Polars로 읽음)
- 실제 데이터가 없을 때 테스트해 볼 수 있는 가상 샘플 데이터 생성
- 회사마다 다른 컬럼명(거래처/적요/계정과목/상대계정 등)을 화면에서 직접
  선택해서 매핑, 매핑한 컬럼들을 합친 문맥 텍스트(context_text) 생성
- **PostgreSQL이 이 컴퓨터에 실제로 설치되어 연결되어 있습니다** (winget으로
  무인 설치, 아래 "PostgreSQL 연결 방법"에 설치 과정을 그대로 기록함).
  금융기관 Master / Alias Master / Database 상태 화면이 실제 DB로 동작함을
  확인했습니다.
- **FAST PATH 금융기관 정규화** (Exact Match → Alias Match → Fuzzy Match,
  이 순서로만 시도): 등록된 표준명/별칭과 완전히 같으면 즉시 확정하고,
  그렇지 않으면 rapidfuzz로 유사도를 계산해 90점(기본값) 이상일 때만 자동
  확정합니다. AI(Embedding)는 아직 없습니다.
  - 300,000행을 한 줄씩 반복하지 않습니다. 거래처 표현의 **고유값만** 매칭한
    뒤 Polars join으로 전체 행에 결과를 broadcast합니다.
  - "OO농협", "농협유통", "NH투자"처럼 자동 확정하면 안 되는 사례들이 실제로
    90점 미만(45~60점)이 나와 UNRESOLVED로 남는 것을 테스트로 확인했습니다.
- Dashboard에 정규화 방법별 건수(EXACT/ALIAS/FUZZY/UNRESOLVED), 자동
  확정/검토 필요 건수를 실제 계산값으로 표시
- pytest 자동 테스트 34개 (아래 "테스트 실행 결과" 참고)

**아직 구현되지 않은 기능**
- Embedding 기반 AI 추천 (사전에 없는 표현, 예: 오타 "농협은헹"은 지금
  90점 미만이라 UNRESOLVED로 남고 사람이 봐야 함 — 이건 Phase 4~5에서
  Embedding/문맥 재평가로 보완할 부분입니다)
- 문맥 재평가(Context Reranking), 즉 적요/계정과목 등을 보고 후보를 다시
  평가하는 기능 — 지금 FAST PATH는 거래처 이름만 보고 판단합니다
- Human Review 화면과 저장, Feedback 축적
- 회사 제출 금융기관 목록과의 완전성 비교
- normalization_results 등 분석결과를 PostgreSQL에 저장하는 기능 (지금은
  화면에서만 보여주고 DB에 저장하지 않음 — Human Review가 필요해지는
  Phase 5~6에서 저장하도록 만들 계획)
- 대용량(10만/30만 건) 성능 테스트, Excel 결과 다운로드
- 모델 성능(Accuracy/Precision/Recall 등) 평가

이 문서 뒤쪽의 "다음 단계"에 Phase 4부터의 계획이 있습니다.

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
  API가 아니라 내 컴퓨터에서 도는 모델을 씁니다. 즉 분개 데이터가 외부
  서버로 전송되지 않습니다.
- **rapidfuzz** (Phase 3부터): 오타나 지점명이 붙은 표현("농협은행
  부산지점")처럼, 완전히 같지는 않지만 비슷한 문자열을 찾는 데 씁니다.
  AI 모델 없이 문자열 유사도만 계산하므로 빠릅니다.

## 왜 모든 행에 AI를 돌리지 않는가

"NH농협은행"처럼 누가 봐도 명확한 표현이 3만 번 반복된다고 해서, 3만 번 AI
모델을 부르는 것은 느리고 낭비입니다. 그래서:

1. 먼저 정확히 일치하는지, 미리 등록된 별칭 목록에 있는지, 유사도가 아주
   높은지를 빠르게 확인합니다 (FAST PATH: Exact → Alias → Fuzzy, Phase 3에서
   구현 완료). 이 세 가지는 AI 모델을 부르지 않습니다.
2. 이 세 가지로도 확정하지 못한 표현만 AI(Embedding)로 넘깁니다 (AI PATH,
   Phase 4~5에서 구현 예정, 아직 없음).
3. 같은 표현을 이미 처리했다면 결과를 재사용(Cache)합니다. 단, "농협"처럼
   문맥에 따라 뜻이 달라질 수 있는 표현은 문맥까지 같아야 같은 결과를
   재사용합니다.

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
src/normalization_pipeline.py   FAST PATH 파이프라인, Polars broadcast (Phase 3)
tests/                          pytest 자동 테스트
```

## 실행 방법

1. 아래 명령으로 필요한 패키지가 설치된 가상환경을 만듭니다 (이미 만들어져
   있다면 건너뜁니다).

   ```
   python -m venv .venv
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
   4. "금융기관 정규화" → "정규화 실행" 버튼 → 결과 미리보기
   5. "Dashboard" → 방법별 처리 건수 확인

## 테스트 실행 방법 / 결과

```
.venv\Scripts\pytest -v
```

**실제로 실행한 결과 (2026-08-09 기준)**: 34개 전부 통과 (`34 passed`).

- DB 연결 3개 테스트(institution/alias 추가·조회) 포함, 마스터 데이터
  시딩, FAST PATH 매칭(Exact/Alias/Fuzzy), 화면 흐름 전체(마스터 시딩 →
  샘플 생성 → 컬럼 매핑 → 정규화 실행)까지 실제 PostgreSQL에 연결한 상태로
  확인했습니다.
- "OO농협", "농협유통", "NH투자"가 FAST PATH만으로는 자동 확정되지 않는지,
  실제 rapidfuzz 점수(45~60점, threshold 90점 미만)로 검증했습니다.
- 짧은 한글 단어의 한 글자 오타(예: "농협은헹")는 실제로 75점 정도가 나와
  threshold(90점)를 넘지 못하고 검토 필요 상태로 남는다는 것도 실제 점수로
  확인했습니다 — 이 값은 임의로 만든 것이 아니라 rapidfuzz의 실제 계산값입니다.

아직 Embedding, Context Reranking, Human Review, 완전성 비교 관련 테스트는
해당 기능이 구현되지 않아 존재하지 않습니다. 30만 행 대용량 테스트도 아직
실행하지 않았습니다 (Phase 8에서 진행).

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
쌓이면 쓸 수 있는 예시입니다 (Phase 3의 정규화 결과는 아직 이 테이블에
저장하지 않고 화면에서만 보여주므로, 지금은 테이블이 비어 있습니다 —
저장 기능은 Phase 5~6에서 추가할 계획입니다):

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

## 다음 단계 (계획서 기준 Phase 4~9)

- ~~Phase 2: PostgreSQL 연결, 금융기관 Master/별칭 테이블~~ (완료, 실제
  PostgreSQL로 CRUD 테스트까지 확인함)
- ~~Phase 3: 정확 일치, 별칭 매칭, 유사도(rapidfuzz) 매칭~~ (완료. Embedding
  없이 문자열 기반으로만 처리하며, 확정 못한 표현은 UNRESOLVED로 남김)
- Phase 4: Embedding 모델, 후보 검색, 결과 캐시
- Phase 5: 문맥 기반 재평가, 신뢰도 계산, Human Review 화면
- Phase 6: Human Review 결과 저장, Feedback 데이터 축적
- Phase 7: 회사 제출 금융기관 목록 업로드, 완전성 비교(누락 후보 도출)
- Phase 8: 성능 평가, 대용량(30만 건) 테스트, Excel 결과 다운로드
- Phase 9: pytest 보강, README 최종화

각 Phase가 끝나면 실제로 무엇이 되고 무엇이 안 되는지 이 README와 함께
보고합니다.
