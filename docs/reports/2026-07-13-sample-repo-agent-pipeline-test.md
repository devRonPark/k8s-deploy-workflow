# 2026-07-13 샘플 레포 5개 에이전트 파이프라인 테스트 결과

## 1. 요약

현재 브랜치 기준으로 샘플 레포 5개에 대해 본 에이전트 파이프라인을 실행했다.
`AGENTS.md`에 기록한 방식대로 온프렘 OpenAI-compatible 엔드포인트는
`Authorization` 헤더 없이 호출했다.

결과 요약:

> Note: this report was produced before kubeconform preflight became required.
> Because `kubeconform` was skipped, it is evidence of YAML generation and syntax parsing only,
> not a completed Kubernetes schema validation run.

- 모델 엔드포인트 연결: 성공
- 짧은 Chat Completions 호출: 성공 (`ok` 응답)
- 샘플 레포 5개 파이프라인 실행: 모두 예외 없이 완료
- 샘플 레포 5개 manifest YAML 생성: 모두 생성됨
- YAML 문법 검사: 5개 모두 통과
- Kubernetes 스키마 검증: `kubeconform` 미설치로 건너뜀
- `kubectl` dry-run: 선행 스키마 검증이 pass가 아니어서 건너뜀
- 실제 semantic agent 모델 호출: `fastapi-shell-entrypoint` 1개 레포에서 2회 발생, 검증 accepted

## 2. 모델 연동 확인

연동 방식:

- Base URL: `http://192.168.30.167:30000/v1`
- 인증 헤더: 사용하지 않음
- 요청 헤더: `Content-Type: application/json`
- 모델 확인: `GET /models`
- 실제 호출 확인: `POST /chat/completions`

확인된 모델 ID:

```text
/root/.cache/huggingface/models--Qwen--Qwen3-Coder-30B-A3B-Instruct/snapshots/b2cff646eb4bb1d68355c01b18ae02e7cf42d120
```

Smoke test 응답:

```text
ok
```

주의: 현재 production provider 구현은 OpenAI SDK를 사용하며 API key 설정을 요구한다.
이번 테스트에서는 운영 코드를 수정하지 않고, 테스트 실행 스크립트에서만 인증 헤더를 붙이지 않는 HTTP 클라이언트를 주입했다.
파이프라인 자체는 `semantic_mode="openai_compatible"` 경로와 동일한 `OpenAIChatDecisionProvider`를 사용했다.

## 3. 실행 조건

- 대상 샘플 레포:
  - `tests/fixtures/repos/fastapi-fullstack-like`
  - `tests/fixtures/repos/fastapi-shell-entrypoint`
  - `tests/fixtures/repos/jpetstore-like`
  - `tests/fixtures/repos/node-express-like`
  - `tests/fixtures/repos/port-conflict-node`
- Profile: `tests/fixtures/profiles/dev-profile.yaml`
- semantic mode: `openai_compatible`
- 모델 호출 방식: 인증 헤더 없는 주입 클라이언트
- 실행 산출물 루트: `/tmp/agent-pipeline-sample-repos-1783906446`
- 요약 JSON: `/tmp/agent-pipeline-sample-repos-1783906446/summary.json`

각 레포별 파이프라인은 다음 중간 산출물을 생성했다.

```text
00-repository-snapshot.yaml
01-artifact-inventory.yaml
02-evidence-model.yaml
03-rule-inference.yaml
04-semantic-analysis.yaml
05-reconciliation-report.yaml
06-component-model.yaml
07-runtime-model.yaml
08-dependency-model.yaml
09-kubernetes-intent.yaml
10-unresolved-questions.yaml
11-deployment-profile.yaml
12-generated-manifests/
13-validation-report.yaml
14-deployment-readiness-checklist.md
15-smoke-test-plan.yaml
```

## 4. 저장소별 결과

| 샘플 레포 | 파이프라인 | LLM 호출 | Semantic task | 생성 YAML | Deployment | Service | YAML 문법 | 남은 질문 |
|---|---:|---:|---:|---:|---:|---:|---|---:|
| `fastapi-fullstack-like` | 완료 | 0 | 0 | 8 | 2 | 2 | pass | 0 |
| `fastapi-shell-entrypoint` | 완료 | 2 | 1 | 4 | 1 | 1 | pass | 0 |
| `jpetstore-like` | 완료 | 0 | 0 | 3 | 1 | 0 | pass | 0 |
| `node-express-like` | 완료 | 0 | 0 | 4 | 1 | 1 | pass | 0 |
| `port-conflict-node` | 완료 | 0 | 0 | 3 | 1 | 0 | pass | 1 |

`achieved_level`은 모두 0이다. 이는 manifest YAML 생성 실패 때문이 아니라,
현재 실행 환경에 `kubeconform`이 없어 Level 1 스키마 검증을 완료하지 못했기 때문이다.

## 5. 중간 과정 상세

### fastapi-fullstack-like

- 컴포넌트:
  - `backend`: application, workload 있음
  - `frontend`: application, workload 있음
  - `db`: dependency, workload 없음
- runtime command:
  - `backend`: Dockerfile CMD에서 결정
  - `frontend`: Dockerfile CMD에서 결정
- semantic task:
  - 생성되지 않음. 결정론 evidence로 runtime command가 충분히 확인됨.
- deferred:
  - `db`는 dependency라 workload 생성 대상에서 제외됨 (`role_dependency_no_workload`)
- 생성 manifest:
  - `backend/deployment.yaml`
  - `backend/ingress.yaml`
  - `backend/secret.yaml`
  - `backend/service.yaml`
  - `backend/serviceaccount.yaml`
  - `frontend/deployment.yaml`
  - `frontend/service.yaml`
  - `frontend/serviceaccount.yaml`

### fastapi-shell-entrypoint

- 컴포넌트:
  - `backend`: application, workload 있음
- runtime command gap:
  - `shell_script_entrypoint`
  - Dockerfile entrypoint가 shell script를 가리켜 소스 분석 필요
- semantic task:
  - 1개 생성
  - target field: `/components/backend/runtime/command`
  - task id: `SEM-RC-8BBE34538624`
- 모델 호출:
  - 2회
  - 1번째: 모델이 `inspect_entrypoint_script` 도구 호출 선택
  - 도구 결과: `entrypoint.sh` 1개 파일, 1개 라인 분석
  - 2번째: 모델이 resolution 반환
- 검증 결과:
  - status: `accepted`
  - accepted candidate: `SC-001`
  - evidence ref: `SE-05967378AF36`
- 최종 command:
  - source: `llm_semantic_inference`
  - value: `exec uvicorn main:app --host 0.0.0.0 --port 8000`
- 생성 manifest:
  - `backend/deployment.yaml`
  - `backend/ingress.yaml`
  - `backend/service.yaml`
  - `backend/serviceaccount.yaml`

### jpetstore-like

- 컴포넌트:
  - `root`: application, workload 있음
- runtime command:
  - 명령 값은 확정되지 않음
- semantic task:
  - 생성되지 않음. 이번 MVP semantic task builder가 처리하는 runtime command gap 대상이 아님.
- 생성 manifest:
  - `root/deployment.yaml`
  - `root/ingress.yaml`
  - `root/serviceaccount.yaml`
- 참고:
  - Service는 port가 확정되지 않아 생성되지 않음.

### node-express-like

- 컴포넌트:
  - `root`: application, workload 있음
- runtime command:
  - Dockerfile CMD에서 결정
  - value: `["node", "server.js"]`
- semantic task:
  - 생성되지 않음. 결정론 evidence로 runtime command가 충분히 확인됨.
- 생성 manifest:
  - `root/deployment.yaml`
  - `root/ingress.yaml`
  - `root/service.yaml`
  - `root/serviceaccount.yaml`

### port-conflict-node

- 컴포넌트:
  - `web`: application, workload 있음
- runtime command:
  - Dockerfile CMD에서 결정
  - value: `["node", "server.js"]`
- semantic task:
  - 생성되지 않음. runtime command는 확정됐고, 남은 문제는 port conflict임.
- 남은 질문:
  - `Q-PORT-web`
- 생성 manifest:
  - `web/deployment.yaml`
  - `web/ingress.yaml`
  - `web/serviceaccount.yaml`
- 참고:
  - Service는 port가 확정되지 않아 생성되지 않음.

## 6. 검증 단계 결과

모든 레포의 `13-validation-report.yaml`에서 공통으로 다음 결과가 기록됐다.

```text
yaml_syntax: pass
kubeconform: skipped (tool_not_found)
dry_run: skipped (prior stage not pass)
```

따라서 이번 실행으로 확인된 것은 다음이다.

- 파이프라인이 5개 샘플 레포를 예외 없이 분석한다.
- 중간 모델을 거쳐 Kubernetes intent와 manifest 파일을 생성한다.
- 생성된 YAML은 파싱 가능한 문법이다.
- semantic agent가 필요한 샘플에서는 모델 호출, 도구 호출, 검증기 수락까지 이어진다.

이번 실행으로 확인하지 못한 것은 다음이다.

- Kubernetes 스키마 적합성
- `kubectl apply --dry-run=client` 결과
- 실제 클러스터 배포 가능성

## 7. 결론

현재 브랜치 기준으로 샘플 레포 5개는 모두 실제 manifest YAML 검출 및 생성 경로를 통과했다.
다만 Kubernetes 레벨의 완전한 정상 판정은 `kubeconform`과 `kubectl`이 있는 환경에서 추가 검증해야 한다.

semantic agent 관점에서는 `fastapi-shell-entrypoint` 샘플이 실제 모델 연동을 사용했고,
모델이 shell entrypoint 분석 도구를 선택한 뒤 runtime command 후보를 반환했으며,
Verifier가 해당 후보를 accepted 처리했다.
