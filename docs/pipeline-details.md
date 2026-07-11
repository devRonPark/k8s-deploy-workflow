# Phase 1 파이프라인 상세

> `README.md`의 개요를 넘어서는 기능별 세부 규칙. 코드와 갈리면
> [architecture.md](./architecture.md) §2의 구현 상태 마커가 진실이다.

## Snapshot 모드 (재현성)

`run_phase1_analysis(..., mode=...)`로 분석 입력의 재현성 기준을 선택한다.

| mode | 분석 대상 | 재현성 의미 |
|---|---|---|
| `workspace` (기본) | 현재 working tree | 커밋하지 않은 변경·untracked 파일 포함. `workspace_hash`(분석 대상 파일 내용 해시)가 재현성 키이며, dirty 여부·수정/untracked 파일 목록을 snapshot에 기록 |
| `commit` | `git archive HEAD` 트리 | working tree 상태와 무관하게 **동일 commit → byte-identical 산출물**. 커밋되지 않은 값은 산출물·prompt에 노출되지 않음 |

Snapshot metadata에 `snapshot_mode`, `workspace_hash`, `workspace_dirty`, `modified_files`, `untracked_files`가 포함된다. `commit` 모드에서 git 저장소가 아니면 working tree로 fallback하고 warning을 남긴다.

## Compose 지원 범위

- **override 병합**: Compose 공식 병합 규칙을 따른다 — mapping 재귀 병합, `ports`(host_ip/published/target/protocol 키)·`volumes`(target 키)·`secrets`/`configs` 키 기준 병합, `environment`/`labels` map·list 표현 통합, `command`/`entrypoint`/`healthcheck.test` 교체, `!override`/`!reset` 태그 지원. port 병합 결과는 `docker compose config`와 대조하는 golden test로 검증한다.
- **port 파싱**: `raw` 원문을 항상 보존하고 host IP·IPv6 bracket·protocol·`${VAR}`·`${VAR:-default}`·range를 인식한다. 단일 정수로 확정할 수 없는 값(default 없는 `${VAR}`, range)은 **추측하지 않고** `resolved=false` + `warning`으로 기록한다.
- **environment**: 원문 값은 저장하지 않는다(secret 정책). bare key(`- DEBUG`)는 `source: host_environment`로, 명시적 빈 값과 구분해 기록한다.
- **제한**: env 값 interpolation은 의도적으로 수행하지 않는다(secret 비유출). port range는 개별 포트로 전개하지 않는다.

## Component ownership

- Compose service 후보와 package(manifest) 후보를 **union + reconcile**한다. compose `build.context`가 가리키는 root의 package는 해당 service에 흡수되고, 매칭되지 않는 monorepo package는 별도 component로 남는다.
- **image-only service**(`root_path=None`)는 source root를 소유하지 않아 runtime/framework가 잘못 연결되지 않는다.
- artifact는 **longest-prefix** 규칙으로 가장 구체적인 component에 귀속된다(중첩 package 오귀속 방지).

## Semantic budget

- Semantic tool 호출은 `SemanticToolSession`을 통해 실행되며 task 단위 `BudgetLedger`가 tool call·distinct tool·unique file·source line·schema retry를 **누적 강제**한다. 한도 도달 시 이후 호출은 실행 없이 `budget_exhausted`로 거부되고, 직전까지의 evidence는 보존된다.

## Python requirements

- `requirements.txt`의 `-r`/`-c` include, index/`--hash` 옵션, editable/VCS/direct-URL 참조를 일반 package와 분리한다. VCS URL의 credential은 저장하지 않고 `#egg=` 이름만 남긴다.
