# Kubernetes Deploy Agent MVP Test Matrix

Task 20의 MVP 기준은 10개 fixture를 자동 실행하고, 그중 최소 8개가 사용자 Kubernetes YAML 작성 없이 `manifest-ready`에 도달하는 것이다. 나머지 fixture는 추측 대신 질문 또는 blocked reason을 남겨야 한다.

## 실행 명령

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest \
  tests.acceptance.test_mvp_fixture_matrix \
  tests.acceptance.test_manifest_reproducibility_matrix \
  tests.cli.test_exit_code_matrix -v
```

최종 release gate는 전체 테스트다.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python3 -m unittest discover -s tests -v
```

## Fixture 기준

| Fixture | 기대 상태 | 범위 |
| --- | --- | --- |
| `node-express-like` | READY | 기존 Node 단일 서비스 |
| `python-fastapi-like` | READY | Python/FastAPI 단일 서비스 |
| `java-spring-like` | READY | Java 단일 서비스 |
| `frontend-backend-monorepo` | READY | frontend/backend 모노레포 |
| `compose-multi-service` | READY | Docker Compose 다중 서비스 |
| `secret-candidate-node` | READY | Secret 후보, 기존 Secret 사용 답변 |
| `no-dockerfile-node` | READY | Dockerfile 없음, package metadata 기반 |
| `corrupt-package-node` | READY | 손상된 package manifest, Dockerfile 근거 fallback |
| `fastapi-fullstack-like` | BLOCKED | persistent/stateful dependency design review |
| `port-conflict-node` | WAITING_FOR_USER | conflicting runtime commands |

## 판정 규칙

- READY fixture는 `generated/manifest-bundle.yaml`과 `validation/13-validation-report.yaml`을 생성해야 한다.
- Non-ready fixture는 `agent/questions.yaml` 또는 `profile/deployment-profile.yaml`의 blocked/unresolved reason을 남겨야 한다.
- READY fixture 반복 실행은 generated directory의 path와 bytes가 동일해야 한다.
- CLI matrix는 성공 `0`, 사용 오류 `2`, 질문/답변 오류 `3`, 정책 block `4`, non-resumable/internal class `8` 경로를 검증한다.
