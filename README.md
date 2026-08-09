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

## 지금 실제로 되는 것 / 안 되는 것 (Phase 2 기준)

**실제로 구현되어 동작하는 기능**
- 분개장 CSV/Excel 파일 업로드 (Polars로 읽음)
- 실제 데이터가 없을 때 테스트해 볼 수 있는 가상 샘플 데이터 생성
- 회사마다 다른 컬럼명(거래처/적요/계정과목/상대계정 등)을 화면에서 직접
  선택해서 매핑
- 매핑한 컬럼들을 합쳐 문맥 텍스트(context_text)를 만드는 기능
- PostgreSQL 연결 코드와 테이블 스키마 (SQLAlchemy). **단, 이 컴퓨터에는
  아직 PostgreSQL이 설치되어 있지 않아 실제 연결 테스트는 하지 못했습니다.**
  자동 설치는 하지 않습니다 (아래 "PostgreSQL 연결 방법" 참고).
- 금융기관 Master / Alias Master 화면 (등록·조회·활성/비활성 전환) — DB가
  연결되어 있어야 동작하며, 연결이 안 되어 있으면 화면에 "PostgreSQL 연결이
  필요합니다"라고 표시됩니다 (이 부분은 확인함).
- Database 상태 화면 (연결 여부, 등록된 기관/별칭 수 표시, 비밀번호는 절대
  표시하지 않음)
- pytest 자동 테스트 19개 (아래 "테스트 실행 결과" 참고)

**아직 구현되지 않은 기능, 또는 만들었지만 실제 DB로 검증하지 못한 기능**
(계획서의 Phase 3 이후 + 이번 Phase 2에서 DB 미보유로 미검증된 부분)
- institution_master/institution_alias CRUD 코드에 대한 실제 PostgreSQL
  연결 테스트 (DB가 없어 코드만 작성, 3개 테스트는 skip 처리됨)
- 정확 일치/별칭/유사도(rapidfuzz) 매칭
- Embedding 기반 AI 추천, 문맥 재평가(Context Reranking)
- Human Review 화면과 저장, Feedback 축적
- 회사 제출 금융기관 목록과의 완전성 비교
- 대용량(10만/30만 건) 성능 테스트, Excel 결과 다운로드
- 모델 성능(Accuracy/Precision/Recall 등) 평가

이 문서 뒤쪽의 "다음 단계"에 Phase 3부터의 계획이 있습니다.

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

## 왜 모든 행에 AI를 돌리지 않는가

"NH농협은행"처럼 누가 봐도 명확한 표현이 3만 번 반복된다고 해서, 3만 번 AI
모델을 부르는 것은 느리고 낭비입니다. 그래서:

1. 먼저 정확히 일치하는지, 미리 등록된 별칭 목록에 있는지 빠르게 확인합니다
   (FAST PATH). 이건 계획서의 Phase 3에서 구현됩니다.
2. 사전에 없는 표현, 애매한 표현만 AI(Embedding)로 넘깁니다 (AI PATH,
   Phase 4~5에서 구현).
3. 같은 표현을 이미 처리했다면 결과를 재사용(Cache)합니다. 단, "농협"처럼
   문맥에 따라 뜻이 달라질 수 있는 표현은 문맥까지 같아야 같은 결과를
   재사용합니다.

## 폴더 구조

```
app.py                     Streamlit 화면 진입점
config/settings.yaml       화면 기본값 설정 (샘플 행 수, 미리보기 행 수 등)
data/synthetic/            가상 샘플 데이터 (실제 고객 데이터 절대 넣지 않음)
data/cache/                대용량 파일 캐시용 (Phase 8부터 사용, 아직 비어 있음)
outputs/                   분석 결과 내보내기 (Phase 8부터 사용)
src/                       실제 처리 로직 (데이터 읽기, 컬럼 매핑 등)
src/database/connection.py PostgreSQL 연결 (DATABASE_URL만 사용, 코드에 비밀번호 없음)
src/database/models.py     테이블 정의 (SQLAlchemy)
src/database/repository.py 금융기관 Master/Alias CRUD 함수
tests/                     pytest 자동 테스트
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

4. 사이드바에서 "분개장 업로드" → 파일을 올리거나 "샘플 데이터 생성" 버튼
   클릭 → "컬럼 Mapping"에서 거래처 등 컬럼 선택 → "context_text 생성"
   버튼을 누르면 결과를 미리 볼 수 있습니다.

## 테스트 실행 방법 / 결과

```
.venv\Scripts\pytest -v
```

**실제로 실행한 결과 (2026-08-09 기준)**: 19개 중 16개 통과, 3개는 건너뜀(skip)
(`16 passed, 3 skipped`).

- 통과한 16개: 가상 데이터 생성기, 컬럼 매핑/context_text 생성, CSV 파일
  읽기, 화면 흐름(업로드→매핑→미리보기) 시뮬레이션, 그리고 금융기관
  Master/Alias Master/Database 상태 화면이 **PostgreSQL 미연결 상태에서
  에러 없이 안내 메시지를 보여주는지**까지 확인.
- 건너뛴 3개: 실제 PostgreSQL에 기관/별칭을 추가하고 조회하는 테스트.
  이 컴퓨터에 PostgreSQL이 없어서 "실패"가 아니라 "건너뜀"으로
  처리됐습니다 — 즉 **이 3개는 아직 한 번도 실행되어 성공한 적이 없습니다.**
  PostgreSQL을 연결한 뒤 다시 `pytest`를 돌리면 이 3개도 같이 실행됩니다.

아직 별칭 매칭, 유사도 매칭, Embedding 관련 테스트는 해당 기능이 구현되지
않아 존재하지 않습니다. 30만 행 대용량 테스트도 아직 실행하지 않았습니다
(Phase 8에서 진행).

## PostgreSQL 연결 방법

**현재 이 컴퓨터에는 PostgreSQL이 설치되어 있지 않습니다** (직접 확인함:
`psql` 명령, Windows 서비스, `C:\Program Files\PostgreSQL`, Docker 모두
없음). 프로그램이 자동으로 설치하지 않으므로, 금융기관 Master/Alias
Master/Database 상태 화면을 실제로 써보려면 아래를 **직접** 진행해야
합니다.

1. **PostgreSQL 설치** — https://www.postgresql.org/download/windows/ 에서
   설치 프로그램을 받아 설치합니다. 설치 중 물어보는 관리자(superuser)
   비밀번호를 기억해 두세요.
2. **데이터베이스 생성** — 설치 시 같이 설치되는 "SQL Shell (psql)"을 열고:
   ```sql
   CREATE DATABASE financial_entity_resolution;
   ```
3. **사용자 계정 생성** (관리자 계정을 그대로 써도 되지만, 별도 계정을
   권장합니다):
   ```sql
   CREATE USER app_user WITH PASSWORD '원하는_비밀번호';
   GRANT ALL PRIVILEGES ON DATABASE financial_entity_resolution TO app_user;
   ```
4. **`.env` 파일에 `DATABASE_URL` 설정** — 프로젝트 폴더에 `.env` 파일을
   만들고 (`.env.example`을 복사) 아래처럼 채웁니다:
   ```
   DATABASE_URL=postgresql+psycopg://app_user:원하는_비밀번호@localhost:5432/financial_entity_resolution
   ```
5. **연결 테스트** — Streamlit 앱을 실행한 뒤 사이드바에서 "Database 상태"
   메뉴를 열면 "Connected" 또는 "Not Connected"가 표시됩니다. 또는 터미널에서:
   ```
   .venv\Scripts\pytest tests/test_database.py -v
   ```
   PostgreSQL이 연결되면 이 3개 테스트가 skip 대신 실제로 실행됩니다.

프로그램은 PostgreSQL을 자동으로 설치하거나 서버 설정을 바꾸지 않습니다.
연결에 실패하면 화면과 테스트 모두 "PostgreSQL 연결이 필요합니다"라고
명확히 표시합니다 (자동으로 다른 DB로 대체하지 않습니다).

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

아래 두 쿼리는 Phase 3 이후 `normalization_results`/`human_reviews`에
실제 데이터가 쌓이면 쓸 수 있는 예시입니다 (지금은 테이블만 있고 비어 있음):

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

## 다음 단계 (계획서 기준 Phase 3~9)

- ~~Phase 2: PostgreSQL 연결, 금융기관 Master/별칭 테이블~~ (완료. 단, 실제
  PostgreSQL로 CRUD 테스트하는 것은 이 컴퓨터에 PostgreSQL을 설치한 뒤로
  남아있음)
- Phase 3: 정확 일치, 별칭 매칭, 유사도(rapidfuzz) 매칭
- Phase 4: Embedding 모델, 후보 검색, 결과 캐시
- Phase 5: 문맥 기반 재평가, 신뢰도 계산, Human Review 화면
- Phase 6: Human Review 결과 저장, Feedback 데이터 축적
- Phase 7: 회사 제출 금융기관 목록 업로드, 완전성 비교(누락 후보 도출)
- Phase 8: 성능 평가, 대용량(30만 건) 테스트, Excel 결과 다운로드
- Phase 9: pytest 보강, README 최종화

각 Phase가 끝나면 실제로 무엇이 되고 무엇이 안 되는지 이 README와 함께
보고합니다.
