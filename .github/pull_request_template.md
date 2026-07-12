## 무엇을 / 왜

<!-- 사용자 관점 한 줄 + 근거 -->

## 변경 범위

- [ ] 결정론 경로는 결정론 유지 (LLM 미개입)
- [ ] Secret 값을 prompt·산출물·로그에 노출하지 않음
- [ ] context 문서(`CLAUDE.md`/`AGENTS.md`/`README.md`)의 경로 참조가 실존
- [ ] 모듈 context(`src/CLAUDE.md`, `tests/CLAUDE.md`)를 코드 변경과 함께 갱신

## 검증

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests -v
python3 scripts/validate_context_paths.py .
```

- 실행한 테스트 수 / 결과:
- 실행 안 한 것:

## 남은 사항
