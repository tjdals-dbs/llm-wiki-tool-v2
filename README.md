# LLM Wiki Tool v2

Markdown 기반 LLM Wiki 유지보수 도구입니다. 사용자는 자료를 `raw/` 계층에 직접 두고, 도구는 raw 파일을 수정하지 않은 채 source summary page, concept page, graph, lint 결과를 구성합니다.

## 핵심 흐름

1. `domain.yml`로 지식 도메인을 정의합니다.
2. 사용자가 `raw/` 폴더에 자료를 넣습니다.
3. CLI, MCP tool adapter, 데스크톱 GUI가 같은 코어를 호출해 다음 순서로 처리합니다.
   - raw source scan
   - source summary 생성
   - pending source concept 조직
   - wiki graph 생성
   - wiki lint

## 빠른 실행

```powershell
python scripts/wiki_tool.py --domain examples/finance/domain.yml pipeline
python scripts/lint_wiki.py --domain examples/finance/domain.yml
python scripts/run_mcp_server.py --domain examples/finance/domain.yml --transport stdio
python scripts/run_desktop_gui.py --domain examples/finance/domain.yml
Copy `.env.example` to `.env` to configure the Codex provider.
python scripts/smoke_codex_provider.py --domain examples/finance/domain.yml --question "CAPM은 무엇인가?"
```

## 검증

```powershell
python -m unittest discover -v
python -m compileall wiki_tool scripts tests
python scripts/lint_wiki.py --domain examples/finance/domain.yml
```

## 개인정보 경계

공개 저장소에는 private raw 자료, PDF 원본, 이미지 원본, HTML 원본, API key, local runtime state를 포함하지 않습니다.

- 실제 개인 자료는 루트 `raw/` 또는 도메인별 `raw/`에 두되 커밋하지 않습니다.
- `raw/private/`와 `examples/**/raw/private/`는 스캔 및 공개 예제 경계 밖으로 취급합니다.
- `examples/**/raw/`에는 public-safe 텍스트 fixture만 둡니다. PDF, 이미지, HTML, key/env 파일은 예제 raw에도 커밋하지 않습니다.
- 공개 예제 wiki는 public-safe raw fixture에서 생성된 결과만 포함합니다.
