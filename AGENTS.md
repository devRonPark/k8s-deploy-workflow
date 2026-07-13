# AGENTS.md

**Codex CLI** 나침반. 전체 규칙은 [docs/codex-guidelines.md](./docs/codex-guidelines.md),
모듈별 상세는 각 디렉터리 CLAUDE.md, 코드 진실은 [docs/architecture.md](./docs/architecture.md) §2.

## Scope · Priority

`Superpowers` 플러그인이 설치돼 있다고 가정한다. Superpowers가 개발 프로세스를,
이 파일이 프로젝트별 제약을 정의한다. 충돌은 조용히 해결하지 말고 표면화한다.

1. 현재 사용자 요청 → 2. `AGENTS.md` → 3. 호출된 Superpowers 스킬
→ 4. 승인된 문서·기존 테스트·코드 → 5. Codex 기본값

작업 시작 전 `superpowers:using-superpowers`를 적용하고, 실제 구현 전 필요한 설계 승인을 받는다.
스킬 매핑·git worktree·문서 위치 규칙은 [docs/codex-guidelines.md](./docs/codex-guidelines.md) 참고.

## Architecture Invariants (load-bearing)

- **Deterministic First** — 탐지·파싱·정규화·근거·rule inference는 결정론 유지. 파싱 가능한 곳에 LLM 금지. 동일 입력 → 동일 출력. 시계는 주입한다.
- **Intermediate Models Before YAML** — 저장소→YAML 지름길 금지. 최종 매니페스트는 Intent Model + 검증된 템플릿에서 나온다. free-form LLM YAML은 최종 산출물이 아니다.
- **Evidence Before Conclusions** — `value / source / confidence / classification / evidence_refs` 보존. 관측·rule·LLM 추론을 구분하고 conflict·unresolved를 명시한다. LLM 후보가 고신뢰 결정론 후보를 덮지 않는다.
- **Secret Safety** — Secret 값을 LLM·evidence·log·fixture·산출물에 절대 넣지 않는다. 최소 메타데이터만. Secret 변경엔 non-leak 회귀 테스트 필수.
- **Bounded Semantic Agent** — 결정론 코드가 `SemanticTask` 생성 여부를 결정. 1 task = 1 `target_field`. `allowed_tools`·budget 강제. 저장소 전체를 컨텍스트에 넣지 않는다. 후보는 `llm_semantic_inference`, confidence는 `low`/`medium`, Verifier가 수락을 결정.

## Context Loading

컨텍스트는 작게: `README.md` → 관련 spec/plan/ADR → 대상 모듈+테스트 → 인접 계약. 그 이상은 근거 있을 때만.

```text
src/preanalyzer/analyzer/scanner.py       # snapshot + inventory
src/preanalyzer/analyzer/parsers/         # artifact parsing
src/preanalyzer/analyzer/rule_inference.py # evidence -> candidates
src/preanalyzer/pipeline.py               # orchestration + YAML
```

모듈 세부는 `src/CLAUDE.md`, `tests/CLAUDE.md`. 계층 간 책임을 편의로 옮기지 않는다.

## Local LLM Endpoint

온프렘 OpenAI-compatible 모델 연동 확인은 다음 방식으로 한다.

- Base URL: `http://192.168.30.167:30000/v1`
- `Authorization` 헤더를 넣지 않는다.
- `Content-Type: application/json`만 사용한다.
- 먼저 `GET /models`로 실제 모델 ID를 확인한 뒤, 그 ID로 `POST /chat/completions`를 호출한다.
- 모델 테스트 실패를 API key 문제로 단정하지 말고, 인증 헤더 없는 호출 결과를 먼저 근거로 삼는다.

## Required Tooling

Kubernetes manifest validation work requires project-managed `kubeconform`.

Before agent-run sample repo validation or completion claims involving generated manifests:

```bash
python3 scripts/ensure_kubeconform.py --check
```

If `13-validation-report.yaml` records `kubeconform: skipped`, the sample validation run is incomplete.
Do not report Kubernetes schema validation as complete until kubeconform produces `pass` or `fail`.


## Completion

완료 선언 전 `superpowers:verification-before-completion` 적용 후 최신 실행:

```bash
git status --short && git diff --check
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests -v
python3 scripts/validate_context_paths.py .
```

> Don't: 서브에이전트 보고를 diff·검증 없이 신뢰하지 말 것. 미실행 테스트를 통과로 표현하지 말 것.
> 최종 보고는 비개발자용 한국어 5단 구조 — [docs/codex-guidelines.md](./docs/codex-guidelines.md) 참고.
