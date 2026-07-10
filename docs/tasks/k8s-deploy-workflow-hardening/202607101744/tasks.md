# k8s-deploy-workflow 개선 작업 목록

> 기준: 최신 `main` 브랜치 코드 리뷰 결과  
> 목적: 임의의 외부 저장소를 안전하고 재현 가능하게 분석하고, 후속 LLM 및 Kubernetes Manifest 생성 단계에 신뢰할 수 있는 입력을 제공하기 위한 개선 작업 정리

---

## 우선순위 정의

- **P0**: 보안 또는 데이터 유출 가능성. 즉시 수정 필요
- **P1**: 분석 정확성, 재현성, 안정성에 직접 영향. 다음 릴리스 전 수정 권장
- **P2**: 문서, 유지보수성, 운영 편의성 개선

---

# P0 — 보안

## TASK-001. Phase 1 스캐너의 Symlink 및 Repository Boundary 차단

### 문제

Phase 1 파일 탐색이 `Path.rglob()`와 `Path.is_file()`에 의존하고 있어, 저장소 외부 파일을 가리키는 symbolic link가 분석 대상에 포함될 수 있다.

Semantic tool 계층에는 경로 이탈 방어가 적용되어 있으나 Phase 1 scanner에는 동일한 보호가 없어 보안 경계가 일관되지 않다.

### 대상 파일

- `src/preanalyzer/analyzer/scanner.py`
- 필요 시 공통 경로 검증 유틸리티 추가

### 구현 항목

- [ ] Repository root를 `resolve()`하여 기준 경로로 사용
- [ ] 각 탐색 파일의 실제 경로를 `resolve()`한 뒤 repository 내부인지 검사
- [ ] Repository 외부로 이탈하는 파일 제외
- [ ] Broken symlink 제외
- [ ] Symlink directory 처리 정책 정의
- [ ] 내부 symlink 허용 여부를 명시적으로 결정
- [ ] Scanner와 semantic tools가 동일한 path safety 함수를 사용하도록 공통화
- [ ] 제외된 파일을 warning 또는 scanner metadata에 기록

### 권장 정책

기본 정책은 다음과 같이 설정한다.

```text
외부 경로를 가리키는 symlink: 차단
broken symlink: 차단
저장소 내부 파일을 가리키는 symlink: 정책에 따라 허용 가능
symlink directory: 기본 차단
```

### 완료 조건

- [ ] 저장소 외부 파일의 내용이 inventory, evidence, output에 포함되지 않음
- [ ] 경로 이탈 시 분석 전체가 중단되지 않고 warning으로 기록됨
- [ ] Phase 1과 semantic 계층이 동일한 경로 검증 규칙을 사용함

### 테스트

- [ ] 외부 파일을 가리키는 symlink
- [ ] 내부 파일을 가리키는 symlink
- [ ] 외부 directory를 가리키는 symlink
- [ ] broken symlink
- [ ] `../` 경로 이탈
- [ ] 절대 경로 이탈

---

## TASK-002. 환경변수 및 Credential-bearing URI 기본 비공개화

### 문제

현재 환경변수 이름에 `PASSWORD`, `SECRET`, `TOKEN`, `KEY` 등의 문자열이 포함된 경우에만 값이 제거된다.

다음과 같이 변수 이름에 민감 키워드가 없더라도 credential이 포함된 URI가 산출물에 노출될 수 있다.

```yaml
DATABASE_URL: postgresql://admin:real-password@db:5432/app
REDIS_URL: redis://:real-password@redis:6379
JDBC_URL: jdbc:postgresql://user:password@db/app
SMTP_URL: smtp://account:password@mail.example.com
```

### 대상 파일

- `src/preanalyzer/analyzer/evidence_builder.py`
- `src/preanalyzer/analyzer/rule_inference.py`
- 관련 evidence model
- 관련 serializer 및 테스트

### 구현 항목

- [ ] 환경변수 값을 기본적으로 output에 저장하지 않도록 변경
- [ ] 민감 여부를 변수 이름이 아닌 값의 구조까지 포함해 판정
- [ ] URI의 `userinfo`, password, token, query credential 제거
- [ ] Dependency 분석에 필요한 최소 정보만 구조화하여 저장
- [ ] `${VARIABLE}` 참조 정보만 저장
- [ ] 값 존재 여부와 값 유형만 저장
- [ ] 원문 환경변수 값이 LLM 입력으로 전달되지 않도록 차단
- [ ] 로그와 exception message에도 원문 값이 포함되지 않도록 확인
- [ ] 기존 `_safe_env_fact` 명칭과 역할 재정의

### 권장 Evidence 형식

```yaml
service: backend
name: DATABASE_URL
value_present: true
value_type: uri
contains_credentials: true
referenced_variables:
  - POSTGRES_PASSWORD
sanitized:
  scheme: postgresql
  host: db
  port: 5432
```

### 완료 조건

- [ ] 모든 환경변수 원문이 기본적으로 output에서 제거됨
- [ ] URI 기반 dependency 탐지는 host와 port만으로 동작함
- [ ] Secret 값이 Phase 1 output, semantic input, 로그에 남지 않음
- [ ] 기존 dependency edge 추론 기능이 유지됨

### 테스트

- [ ] `DATABASE_URL`에 user/password 포함
- [ ] `REDIS_URL`에 password 포함
- [ ] JDBC URL에 credential 포함
- [ ] query parameter에 token 포함
- [ ] `${PASSWORD}` 형태의 변수 참조
- [ ] 변수 이름에는 민감 키워드가 없지만 값에 credential 포함
- [ ] 직렬화된 전체 output에 secret 문자열이 존재하지 않는지 검사

예시:

```python
assert "real-password" not in serialized_output
assert "admin:real-password" not in serialized_output
assert "redis://:" not in serialized_output
```

---

# P1 — 재현성

## TASK-003. Commit Snapshot과 Workspace Snapshot 모드 분리

### 문제

Snapshot metadata에는 `git rev-parse HEAD`로 commit SHA를 기록하지만, 실제 분석 대상은 현재 working directory다.

동일 commit에서도 다음 요소로 인해 결과가 달라질 수 있다.

- 수정됐지만 commit하지 않은 파일
- untracked 파일
- 로컬 생성 파일
- build 또는 dist 디렉터리 안의 복제 파일

따라서 다음 재현성 조건을 현재 구조로는 보장할 수 없다.

```text
동일 commit + 동일 profile + 동일 rules_version = 동일 산출물
```

### 대상 파일

- `src/preanalyzer/analyzer/scanner.py`
- snapshot model
- CLI 또는 pipeline option
- output metadata
- determinism tests

### 구현 항목

- [ ] `commit` 모드와 `workspace` 모드 분리
- [ ] 기본 모드 결정
- [ ] 각 모드의 재현성 의미를 README에 명시
- [ ] Snapshot metadata에 `snapshot_mode` 추가
- [ ] Workspace mode에서 dirty 상태 기록
- [ ] Workspace mode에서 untracked file 목록 기록
- [ ] Workspace content hash 생성
- [ ] Output 재현성 키에 snapshot mode와 workspace hash 반영

### Commit Mode

- [ ] `git ls-tree -r --name-only <commit>`으로 파일 목록 결정
- [ ] `git show <commit>:<path>` 또는 Git blob API로 파일 내용 읽기
- [ ] Working tree 변경사항과 untracked 파일 무시
- [ ] 동일 commit에 대해 동일 input 보장

### Workspace Mode

권장 metadata:

```yaml
snapshot_mode: workspace
commit_sha: abcdef1234
workspace_dirty: true
workspace_hash: sha256:...
modified_files:
  - compose.yaml
untracked_files:
  - local-compose.yaml
```

### 완료 조건

- [ ] Commit mode에서 dirty working tree가 결과에 영향을 주지 않음
- [ ] Workspace mode에서 파일 변경 시 workspace hash가 변경됨
- [ ] 동일 input에 대해 동일 output hash가 생성됨
- [ ] Snapshot mode가 모든 output metadata에 기록됨

### 테스트

- [ ] 동일 commit, clean workspace
- [ ] 동일 commit, modified tracked file
- [ ] 동일 commit, untracked file
- [ ] 동일 commit, generated file
- [ ] 서로 다른 commit
- [ ] Workspace hash 안정성
- [ ] Commit mode output byte-level determinism

---

# P1 — Compose 정확성 및 안정성

## TASK-004. Compose Override 병합 규칙 정합성 확보

### 문제

현재 override 병합은 `environment`와 `labels` 일부만 병합하고 나머지 필드는 override 값으로 교체한다.

이는 Compose 공식 병합 규칙과 다르며, `ports`, `volumes`, `secrets`, `configs` 등의 결과가 실제 Docker Compose 동작과 달라질 수 있다.

### 대상 파일

- `src/preanalyzer/analyzer/parsers/compose.py`
- Compose parser tests
- Pipeline override tests

### 권장 구현 방식

우선순위 1:

```bash
docker compose   -f compose.yaml   -f compose.override.yaml   config --format json
```

Compose CLI를 정규화기로 사용하고, 정규화 결과를 내부 model로 변환한다.

우선순위 2:

외부 CLI를 사용할 수 없다면 Compose 병합 규칙을 내부 구현한다.

### 구현 항목

- [ ] Mapping 재귀 병합
- [ ] 일반 sequence 연결
- [ ] `ports` 고유 키 기준 병합
- [ ] `volumes` container target 기준 병합
- [ ] `secrets` 병합
- [ ] `configs` 병합
- [ ] `environment` map/list 표현 통합
- [ ] `labels` map/list 표현 통합
- [ ] `command` 교체 규칙
- [ ] `entrypoint` 교체 규칙
- [ ] `healthcheck.test` 교체 규칙
- [ ] `!reset` 지원
- [ ] `!override` 지원
- [ ] 파일별 interpolation 적용 순서 검증

### 완료 조건

- [ ] 분석 결과가 `docker compose config` 결과와 일치
- [ ] Base와 override의 port가 규칙대로 병합됨
- [ ] Volume target 충돌 시 override가 정상 적용됨
- [ ] Map/list 형태가 혼용돼도 동일한 normalized 결과 생성

### 테스트

- [ ] Base port + override port
- [ ] 동일 target port override
- [ ] Volume target override
- [ ] Environment map + list 혼용
- [ ] Labels map + list 혼용
- [ ] command/entrypoint 교체
- [ ] `!reset`
- [ ] `!override`
- [ ] 3개 이상의 Compose file 병합
- [ ] Docker Compose CLI 결과와 golden test 비교

---

## TASK-005. Compose Port Parser의 Interpolation 및 Range 지원

### 문제

현재 compact port 문자열을 즉시 `int()`로 변환하여 다음 표현에서 예외가 발생할 수 있다.

```yaml
ports:
  - "${HTTP_PORT:-8080}:80"
  - "${HTTP_PORT}:80"
  - "8000-8005:80-85"
  - "[::1]:8080:80"
```

### 대상 파일

- `src/preanalyzer/analyzer/parsers/compose.py`
- Compose port model
- 관련 tests

### 구현 항목

- [ ] 원문 `raw` 값 보존
- [ ] host IP 파싱
- [ ] IPv6 bracket 표현 지원
- [ ] host port 파싱
- [ ] container port 파싱
- [ ] protocol 파싱
- [ ] port range 지원
- [ ] `${VAR}` interpolation 표현 지원
- [ ] `${VAR:-default}` 기본값 지원
- [ ] 해석 불가능한 값은 exception 대신 unresolved로 기록
- [ ] Long syntax 지원
- [ ] `mode`, `name`, `app_protocol` 등 long syntax 필드 보존 검토

### 권장 모델

```python
class ComposePort(BaseModel):
    raw: str
    host_ip: str | None = None
    host_port: int | None = None
    container_port: int | None = None
    protocol: str | None = None
    resolved: bool
    resolution_source: str | None = None
    warning: str | None = None
```

### 완료 조건

- [ ] 정상적인 Compose port 표현이 pipeline 전체 실패를 일으키지 않음
- [ ] 미확정 값은 추측하지 않고 unresolved로 기록
- [ ] Port 원문과 해석 결과가 함께 보존됨

### 테스트

- [ ] `"8080:80"`
- [ ] `"127.0.0.1:8080:80"`
- [ ] `"[::1]:8080:80"`
- [ ] `"8080:80/tcp"`
- [ ] `"8000-8005:80-85"`
- [ ] `"${HTTP_PORT:-8080}:80"`
- [ ] `"${HTTP_PORT}:80"`
- [ ] Long syntax
- [ ] 잘못된 port 문자열

---

## TASK-006. Dockerfile 및 Compose Parser 오류 격리

### 문제

일부 parser는 `try_parse_*`를 통해 parsing 오류를 warning으로 변환하지만 Dockerfile과 Compose parser는 예외를 pipeline 밖으로 전파할 수 있다.

한 개의 손상된 파일 때문에 전체 Phase 1 산출물이 생성되지 않을 수 있다.

### 대상 파일

- `src/preanalyzer/pipeline.py`
- Dockerfile parser
- Compose parser
- 공통 parser result model
- parser warning tests

### 구현 항목

- [ ] 모든 parser가 동일한 `ParseResult` 형식 사용
- [ ] Syntax error를 warning으로 변환
- [ ] Artifact presence는 유지
- [ ] Parsed facts만 생략
- [ ] Warning에 parser type, path, error code 기록
- [ ] Warning message에서 민감 값 제거
- [ ] Fatal/non-fatal 오류 구분
- [ ] 복수 parser 실패 시에도 나머지 분석 계속
- [ ] Output에 parser coverage 또는 parsing status 기록

### 권장 모델

```python
class ParseResult[T](BaseModel):
    value: T | None
    warnings: list[ParseWarning]
    fatal: bool = False
```

### 권장 Warning 형식

```yaml
path: compose.yaml
parser: compose
code: invalid_yaml
message: YAML parsing failed
fatal: false
```

### 완료 조건

- [ ] 잘못된 Compose 파일이 있어도 `00~03` 산출물 생성
- [ ] 잘못된 Dockerfile이 있어도 나머지 artifact 분석
- [ ] 오류 파일은 inventory에 유지
- [ ] Warning만으로 원인과 위치를 식별 가능

### 테스트

- [ ] Invalid Compose YAML
- [ ] Unsupported Compose tag
- [ ] Invalid Dockerfile instruction
- [ ] Invalid UTF-8
- [ ] 빈 파일
- [ ] 여러 parser가 동시에 실패
- [ ] 일부 파일 실패 후 정상 산출물 생성

---

# P1 — Component 추론 정확성

## TASK-007. Component와 Artifact Ownership 모델 재설계

### 문제

현재 Compose component가 하나라도 존재하면 package 기반 component 후보가 모두 무시될 수 있다.

또한 Compose가 없는 monorepo의 여러 package가 하나의 `root` component로 합쳐질 수 있고, image-only 서비스가 root package artifact를 잘못 소유하는 것으로 판정될 가능성이 있다.

### 대상 파일

- `src/preanalyzer/analyzer/rule_inference.py`
- package parsers
- component model
- monorepo tests

### 구현 항목

- [ ] Compose component와 package component 후보를 union
- [ ] 중복 후보 reconciliation 로직 추가
- [ ] `build.context` 기반 source ownership 적용
- [ ] image-only 서비스에 source package fact를 연결하지 않음
- [ ] Artifact path와 component root 간 longest-prefix 매칭 적용
- [ ] Root component의 의미 재정의
- [ ] npm/pnpm/yarn workspace 탐지
- [ ] Maven module 탐지
- [ ] Gradle settings 기반 module 탐지
- [ ] Python monorepo 구조 탐지 검토
- [ ] 하나의 source root가 복수 서비스에 연결되는 경우 정책 정의
- [ ] Generated artifact와 source artifact 구분 검토

### 권장 구조

```python
compose_candidates = infer_compose_components(evidence)
package_candidates = infer_package_components(evidence)

component_candidates = reconcile_components(
    compose_candidates=compose_candidates,
    package_candidates=package_candidates,
)
```

### Ownership 규칙

1. 명시적인 `build.context` 우선
2. 명시적인 Dockerfile 경로 반영
3. Artifact path에 대한 longest-prefix root match
4. image-only service는 source ownership 없음
5. 근거가 부족하면 연결하지 않고 unresolved로 기록

### 완료 조건

- [ ] Compose 존재 여부와 무관하게 package component 탐지
- [ ] Monorepo의 각 application이 별도 component로 식별
- [ ] Image-only service에 잘못된 runtime/framework가 연결되지 않음
- [ ] Component마다 source root와 ownership 근거가 기록됨

### 테스트

- [ ] API build + Postgres image-only Compose
- [ ] NPM workspace monorepo
- [ ] Maven multi-module project
- [ ] Gradle multi-project
- [ ] Root app + nested worker
- [ ] 동일 source root를 사용하는 복수 service
- [ ] Compose 없는 package-only monorepo
- [ ] Build context가 repository root가 아닌 경우

---

# P1 — Semantic 실행 통제

## TASK-008. Semantic Tool 누적 Budget Ledger 도입

### 문제

Semantic model에 tool call, file count, source line budget이 정의되어 있으나 각 tool의 개별 호출 제한 위주로 적용된다.

여러 번의 호출을 합산하면 task 전체 budget을 초과할 수 있다.

### 대상 파일

- `src/preanalyzer/semantic/`
- semantic executor 또는 orchestrator
- semantic budget model
- tool wrappers
- 관련 tests

### 구현 항목

- [ ] Task 단위 `BudgetLedger` 추가
- [ ] Tool call 누적 횟수 관리
- [ ] Distinct tool 누적 관리
- [ ] 읽은 파일의 unique set 관리
- [ ] 반환된 source line 누적 관리
- [ ] Schema retry 누적 관리
- [ ] Tool 실행 전 budget 사전 검사
- [ ] Tool 실행 후 실제 사용량 반영
- [ ] Budget 초과 상태를 구조화된 결과로 반환
- [ ] 부분 evidence 보존 정책 정의
- [ ] Budget 사용량을 final semantic output에 기록
- [ ] 병렬 tool 실행 시 race condition 방지

### 권장 모델

```python
class BudgetLedger(BaseModel):
    tool_calls: int = 0
    distinct_tools: set[str] = set()
    files_read: set[str] = set()
    source_lines_returned: int = 0
    schema_retries: int = 0
```

### 권장 종료 상태

```yaml
status: budget_exhausted
budget:
  max_tool_calls: 4
  used_tool_calls: 4
  max_source_lines: 400
  used_source_lines: 400
partial_evidence_preserved: true
```

### 완료 조건

- [ ] Task 전체 사용량이 정의된 budget을 초과하지 않음
- [ ] 동일 파일의 반복 읽기 정책이 일관됨
- [ ] Budget 초과 시 LLM이 추가 tool을 호출하지 못함
- [ ] 종료 이유가 명확히 기록됨

### 테스트

- [ ] Tool call 수 초과
- [ ] Distinct tool 수 초과
- [ ] Unique file 수 초과
- [ ] 누적 source line 초과
- [ ] Schema retry 초과
- [ ] 동일 파일 반복 읽기
- [ ] Budget 마지막 경계값
- [ ] 부분 결과 보존

---

# P2 — Parser 정확성

## TASK-009. Bare Environment Key 의미 보존

### 문제

다음 Compose 표현은 host environment의 값을 전달하는 의미다.

```yaml
environment:
  - DEBUG
```

이를 빈 문자열로 처리하면 “값이 비어 있음”과 “host environment에서 해석됨”을 구분할 수 없다.

### 구현 항목

- [ ] Bare key를 빈 문자열로 변환하지 않음
- [ ] `source=host_environment` 기록
- [ ] `resolved=false` 기록
- [ ] 실제 환경변수 값을 자동으로 읽지 않음
- [ ] Map 형태의 `DEBUG:`와 list 형태의 `DEBUG` 의미 비교
- [ ] Secret redaction 정책과 통합

### 권장 형식

```yaml
name: DEBUG
value_present: unknown
source: host_environment
resolved: false
```

### 테스트

- [ ] `environment: ["DEBUG"]`
- [ ] `environment: ["DEBUG="]`
- [ ] `environment: {DEBUG: null}`
- [ ] `environment: {DEBUG: ""}`

---

## TASK-010. requirements.txt 옵션 및 Include 구문 분리

### 문제

주석이 아닌 모든 행을 package dependency로 처리하면 다음 값이 가짜 package로 기록될 수 있다.

```text
-r requirements-base.txt
--index-url https://packages.example.com/simple
-e git+https://example.com/repo.git#egg=myapp
```

### 대상 파일

- Python dependency parser
- 관련 model 및 tests

### 구현 항목

- [ ] `packaging.requirements.Requirement` 활용 검토
- [ ] 일반 requirement 분리
- [ ] `-r`, `--requirement` include 분리
- [ ] `-c`, `--constraint` 분리
- [ ] index option 분리
- [ ] editable dependency 분리
- [ ] VCS/direct URL dependency 분리
- [ ] Environment marker 보존
- [ ] Hash option 처리
- [ ] Line continuation 처리
- [ ] Parse failure를 warning으로 기록

### 완료 조건

- [ ] Option이 package 이름으로 등록되지 않음
- [ ] Include 관계가 evidence에 기록됨
- [ ] Direct reference와 일반 package가 구분됨

---

# P2 — 문서 및 프로젝트 상태

## TASK-011. README 구현 현황 최신화

### 문제

README의 Step 7 이후 구현 상태와 실제 source tree가 일치하지 않을 수 있다.

현재 semantic task builder, verifier, tools 및 model이 존재하므로 미착수로만 표기하면 프로젝트 상태를 잘못 전달한다.

### 구현 항목

- [ ] 현재 구현된 기능 목록 갱신
- [ ] 구현 중인 기능과 미구현 기능 분리
- [ ] LLM executor/orchestrator 상태 명시
- [ ] Semantic tool 보안 경계 설명
- [ ] Budget enforcement 구현 상태 명시
- [ ] Test count를 자동 생성하거나 고정 숫자 제거
- [ ] Snapshot mode 의미 문서화
- [ ] Secret 처리 정책 문서화
- [ ] Compose 지원 범위와 제한사항 문서화

### 권장 상태 표기

```text
Step 7: Semantic gap task builder 구현
Step 8: LLM executor 미구현
Step 9: Constrained semantic tools 및 verifier PoC 구현
Budget ledger: 미구현
Manifest generation: 미구현
```

### 완료 조건

- [ ] README와 source tree의 구현 상태가 일치
- [ ] 사용자가 현재 가능한 기능과 불가능한 기능을 구분 가능
- [ ] 보안 및 재현성 보장 범위가 명확함

---

# 공통 품질 개선

## TASK-012. 공통 Path Safety 모듈 도입

### 목적

Scanner, parser, semantic tools가 서로 다른 경로 검증 규칙을 구현하지 않도록 통합한다.

### 구현 항목

- [ ] `resolve_repository_path()` 추가
- [ ] `ensure_within_repository()` 추가
- [ ] `ensure_within_component()` 추가
- [ ] Symlink 정책 옵션화
- [ ] 민감 파일명 차단 정책 통합
- [ ] 파일 크기 제한 통합
- [ ] Binary 및 encoding 검사 통합
- [ ] 공통 error code 정의

---

## TASK-013. 공통 Parser Result 및 Warning 체계 도입

### 목적

Parser마다 다른 예외 처리 방식을 통합하고, pipeline이 부분 실패를 안정적으로 처리하도록 한다.

### 구현 항목

- [ ] `ParseResult[T]` 도입
- [ ] `ParseWarning` schema 통합
- [ ] Error code enum 정의
- [ ] Fatal/non-fatal 구분
- [ ] Warning deduplication
- [ ] Warning deterministic ordering
- [ ] 민감 정보 없는 message 작성
- [ ] Output schema에 parser status 추가

---

## TASK-014. Security 및 Determinism Regression Test Suite 추가

### 보안 테스트

- [ ] Symlink path escape
- [ ] Secret-bearing URI
- [ ] Query parameter token
- [ ] `.env` 파일 접근 차단
- [ ] Private key 파일 접근 차단
- [ ] Error message secret leakage
- [ ] Log secret leakage
- [ ] Oversized file
- [ ] Binary file
- [ ] Invalid UTF-8

### 재현성 테스트

- [ ] 동일 commit의 byte-identical output
- [ ] Dirty workspace 영향 분리
- [ ] Untracked file 영향 분리
- [ ] File traversal order 독립성
- [ ] Warning ordering 안정성
- [ ] YAML key ordering 안정성
- [ ] Timestamp 제거 또는 고정
- [ ] Hash 계산 안정성

### Compose 테스트

- [ ] Official merge behavior golden tests
- [ ] Interpolation
- [ ] Port ranges
- [ ] Long syntax
- [ ] Bare environment keys
- [ ] Invalid YAML isolation

### Monorepo 테스트

- [ ] npm workspace
- [ ] Maven multi-module
- [ ] Gradle multi-project
- [ ] Compose와 package component 혼합
- [ ] Image-only dependency services

---

# 권장 구현 순서

## Milestone 1 — Security Hardening

- [ ] TASK-001 Symlink 및 repository boundary 차단
- [ ] TASK-002 환경변수 및 URI 기본 비공개화
- [ ] TASK-012 공통 Path Safety 모듈
- [ ] TASK-014 보안 회귀 테스트

### Exit Criteria

- Repository 외부 파일 접근 불가
- Secret 원문이 output, prompt, log에 존재하지 않음
- 보안 회귀 테스트 전체 통과

---

## Milestone 2 — Reproducibility and Parser Resilience

- [x] TASK-003 Snapshot mode 분리
- [x] TASK-006 Parser 오류 격리
- [x] TASK-013 공통 Parser Result
- [x] TASK-014 재현성 테스트

### Exit Criteria

- Commit mode에서 동일 commit의 산출물이 byte-level로 동일
- 일부 artifact parsing 실패가 전체 pipeline 실패로 이어지지 않음
- 모든 parser warning이 동일 schema 사용

---

## Milestone 3 — Compose Compatibility

- [x] TASK-004 Compose override 병합
- [x] TASK-005 Port parser 개선
- [x] TASK-009 Bare environment 처리
- [x] Compose golden tests 추가

### Exit Criteria

- 주요 Compose 병합 결과가 `docker compose config`와 일치
- 정상적인 interpolation과 port 표현이 분석 중단을 일으키지 않음
- 미확정 값이 추측 없이 unresolved로 기록됨

---

## Milestone 4 — Component and Semantic Accuracy

- [x] TASK-007 Component ownership 재설계
- [x] TASK-008 Semantic budget ledger
- [x] TASK-010 Python requirements parser 개선

### Exit Criteria

- Monorepo component가 source root 단위로 식별됨
- Image-only service에 source runtime이 잘못 연결되지 않음
- Semantic task 전체 budget이 중앙에서 강제됨

---

## Milestone 5 — Documentation and Release Readiness

- [ ] TASK-011 README 최신화
- [ ] 전체 acceptance test 실행
- [ ] 지원 범위 및 제한사항 문서화
- [ ] Release checklist 작성

### Exit Criteria

- README와 실제 구현 상태 일치
- 보안, 재현성, Compose 지원 범위가 명확히 문서화
- 모든 P0/P1 task 완료
- CI에서 전체 regression suite 통과

---

# Definition of Done

각 Task는 다음 조건을 모두 만족해야 완료로 처리한다.

- [ ] 구현 코드 작성
- [ ] 단위 테스트 추가
- [ ] 회귀 테스트 추가
- [ ] 기존 테스트 통과
- [ ] 보안 관련 변경은 secret leakage test 포함
- [ ] Output schema 변경 시 migration 또는 version update
- [ ] README 또는 설계 문서 업데이트
- [ ] Error와 warning이 deterministic한 순서로 출력
- [ ] 사용자 입력 저장소의 일부 오류가 전체 분석 실패로 이어지지 않음
- [ ] 추측한 값과 확인된 값이 명확히 구분됨

---

# 최종 완료 기준

다음 조건이 충족되면 최신 코드 리뷰에서 확인된 핵심 위험이 해소된 것으로 판단한다.

- [ ] Repository 외부 파일 접근 차단
- [ ] 환경변수 및 credential 원문 비유출
- [ ] Commit 기반 분석 결과 재현성 보장
- [ ] Compose 병합 결과의 공식 동작 정합성 확보
- [ ] Parser 부분 실패 격리
- [ ] Monorepo component ownership 정확성 확보
- [ ] Semantic task 누적 budget 강제
- [ ] README와 실제 구현 상태 일치
- [ ] P0 및 P1 regression test 전체 통과
