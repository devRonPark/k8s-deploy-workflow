# AI-Readiness 98/100 — Ralph Loop Spec

> 루프가 매 반복 읽는 **지속 상태 스펙**. 진행상태의 유일한 근거(source of truth)는
> 체크박스가 아니라 스코어러 출력이다. 매 반복 스코어러를 돌려 카테고리 점수로
> "무엇이 남았는지"를 판정한다. (Ralph 원칙: ground truth에서 상태를 도출)

## 목표 / 정지 조건

- **목표: 총점 ≥ 98/100 (등급 AI-Native).**
- 정지: 스코어러 `total >= 98`. 달성 즉시 루프 종료.
- 정직성 제약: **`pnpm-workspace.yaml` 등 JS 모노레포 매니페스트를 Python repo에 넣지 않는다.**
  D 카테고리 workspace +2는 의도적으로 포기 → 정직한 상한 98.

## 검증 명령 (매 반복 필수)

```bash
python /Users/a1234/.claude/skills/ai-readiness-cartography/scripts/score.py . \
  --json docs/ai-readiness-score.json --quiet
python -c "import json;d=json.load(open('docs/ai-readiness-score.json'));print(d['total'],{k:v['score'] for k,v in d['categories'].items()})"
```

## 카테고리별 목표 · 트리거 (score.py 역산)

| Cat | 목표 | 스코어러 트리거 | 액션 |
|---|---|---|---|
| A | 15 | `covered/total*15` + root CLAUDE.md | `src/CLAUDE.md`,`tests/CLAUDE.md` 신설 |
| B | 20 | context 7개 전부 5조건 | 아래 B-체크리스트 |
| C | 20 | 모듈 context 4섹션 + tribal store(adr 이미 있음) | src·tests CLAUDE.md에 4섹션 |
| D | 13 | arch +6·mermaid +3·deps섹션≥3파일 +4 (workspace +2 포기) | context 1곳에 ```mermaid, deps섹션 3파일 |
| E | 15 | ref +5·CODEOWNERS+PR +4·task +4·evals +2 | 아래 E-체크리스트 |
| F | 10 | drift0 +6·ctx-CI +2·hook +2 | context CI + `.husky/pre-push` |
| G | 5 | evals +3·metric +1·telemetry힌트 +1 | `evals/`+`agent-results.json`+CLAUDE.md 1줄 |

### B-체크리스트 — context file 7개 **각각** 충족
1. 10–80줄 (`AGENTS.md` 327·`README.md` 169 → 압축; 상세는 `docs/architecture.md`로 이관, 정보손실 0)
2. ```bash 펜스 1개
3. 고유 경로참조 ≥3 (예: `src/preanalyzer/analyzer/scanner.py`)
4. 비자명 마커 1개 (`Note:` / `주의` / `Gotcha` / `Important:`)
5. 상대 마크다운 링크 1개 (`[arch](../docs/architecture.md)`)

대상 7파일: `CLAUDE.md`, `AGENTS.md`, `README.md`, `docs/tasks/semantic-agent-tasks/README.md`,
`tests/fixtures/repos/jpetstore-like/README.md`, `src/CLAUDE.md`(신규), `tests/CLAUDE.md`(신규).

### E-체크리스트
- E1: `README.md`의 산문 `Dockerfile/compose/package.json`을 백틱 분리 → 경로 오인식 제거 (ref 7/7)
- E2: `.github/CODEOWNERS` + `.github/pull_request_template.md`
- E3: `.github/workflows/context-validate.yml` + `.husky/pre-push` (pyproject 이미 있음)
- E4: `evals/` 디렉터리

### 신규 CLAUDE.md 필수 섹션 (C용, B와 호환)
`## Purpose / Owns` · `## Common Patterns` · `> Note:` 마커 · `## Dependencies` (`depends on ...`)
\+ ```bash 펜스 · 경로참조 ≥3 · 상대링크. 10–80줄 유지.

## 가드레일 (어기면 가짜 AI-ready)
- fixture README 수정 전 `grep -rl jpetstore-like tests/` 로 참조 테스트 확인. 깨지면 fixture 로더도 같이 수정.
- AGENTS.md 상세는 삭제 말고 `docs/architecture.md`로 이관 (usability 보존).
- 코드(hook/워크플로/eval) 작성 시 superpowers TDD: 검증 로직엔 runnable self-check.
- context file의 모든 경로참조는 실존해야 함 (E1 회귀 금지). 추가 후 스코어러로 재확인.

## 완료 후
- `git add -A && git commit` (스텝별 원자 커밋).
- 최종 스코어러 total 출력으로 98 증명. 이후 루프 정지.
