# Semantic Agent Remaining Tasks

이 디렉터리는 `k8s-deploy-workflow`의 Semantic Agent MVP 구현을 위한 남은 작업을 순서대로 나눈 Codex CLI Task 문서다.

## 전제

- 대상 모델은 20B~30B급 On-Premise LLM이다.
- 결정론적 분석이 항상 먼저 실행된다.
- Semantic Agent 실행 여부는 결정론적 코드가 판단한다.
- Agent 내부에서만 LLM이 허용된 Tool 호출을 선택한다.
- Tool은 read-only다.
- LLM Candidate의 최대 confidence는 `medium`이다.
- Verifier를 통과하지 않은 Candidate는 downstream에서 사용하지 않는다.
- 최종 Dockerfile 및 Kubernetes Manifest 생성은 결정론적 Renderer 책임이다.

## 관련 코드 · 문서

상위 아키텍처는 [architecture.md](../../architecture.md), 개발 규칙은
[codex-guidelines.md](../../codex-guidelines.md) 참고. 현재 준비된 결정론 지원 코드:

```text
src/preanalyzer/models/semantic.py       # Semantic 도메인 모델
src/preanalyzer/semantic/verifier.py     # Deterministic Semantic Verifier
tests/unit/test_semantic_verifier.py     # verifier 단위 테스트
```

## 현재 완료 상태

다음 단계까지 구현 및 커밋 완료된 상태를 전제로 한다.

1. Semantic 도메인 모델
2. Deterministic Runtime Command Resolver
3. Runtime Command Semantic Task Builder
4. Read-only Semantic Tools
5. Deterministic Semantic Verifier

## 실행 순서

1. `TASK-05-bounded-agent-state-machine.md`
2. `TASK-06-openai-compatible-qwen-provider.md`
3. `TASK-07-pipeline-integration.md`
4. `TASK-08-onprem-evaluation-harness.md`
5. `TASK-09-prompt-and-tool-optimization.md`
6. `TASK-10-next-semantic-task-review.md`

각 Task는 반드시 이전 Task의 테스트와 커밋이 완료된 뒤 실행한다.

## 권장 저장 위치

```text
docs/tasks/semantic-agent/
├── README.md
├── TASK-05-bounded-agent-state-machine.md
├── TASK-06-openai-compatible-qwen-provider.md
├── TASK-07-pipeline-integration.md
├── TASK-08-onprem-evaluation-harness.md
├── TASK-09-prompt-and-tool-optimization.md
└── TASK-10-next-semantic-task-review.md
```

## 단계별 공통 완료 조건

각 Task 종료 시 다음을 확인한다.

```bash
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=src \
.venv/bin/python3 -m unittest discover -s tests -v

git diff --check
git status --short
```

- 기존 테스트를 삭제하거나 약화하지 않는다.
- 새 파일이 untracked로 남지 않게 한다.
- 현재 Task 범위를 넘어선 구현은 제거한다.
- 완료 보고 내용을 검토한 뒤 별도 커밋한다.
