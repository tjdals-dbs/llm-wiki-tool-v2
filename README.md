# LLM Wiki Tool v2

LLM Wiki Tool v2는 로컬 파일 기반 지식 자료를 Markdown wiki로 정리하고, MCP tool과 데스크톱 GUI를 통해 에이전트가 검색, 답변, 유지보수를 수행할 수 있게 하는 위키 하네스입니다.

사용자는 자료를 `raw/` 폴더에 직접 넣습니다. 도구는 원본을 수정하지 않고 source summary page를 만들고, 그 source evidence를 바탕으로 concept page를 승격하거나 병합합니다. 이후 Markdown link 기반 graph를 생성하고 lint로 위키 구조를 점검합니다.

이 저장소의 예제는 금융투자론 도메인을 사용하지만, 제품 자체는 특정 도메인 전용이 아닙니다. `domain.yml`과 `raw/` 내용을 바꾸면 다른 지식 도메인의 wiki를 만들 수 있습니다.

## 핵심 개념

- `raw/` 불변 원본 계층: 사용자가 넣은 원본 자료가 머무는 계층입니다. 앱, 스크립트, MCP tool, agent는 raw 파일을 수정, 이동, 삭제하지 않습니다.
- source summary page: 하나의 raw source를 사람이 읽을 수 있는 요약 문서로 정리한 페이지입니다. `Summary`, `Key Points`, `Evidence`, `Candidate Concepts`, `Quality Review`를 포함합니다.
- concept page: source summary의 evidence를 바탕으로 합성한 durable wiki page입니다. 기존 concept와 겹치면 새 페이지를 만들기보다 병합합니다.
- graphify: Markdown link와 source evidence 관계를 `wiki/graph/graph.json`으로 만들고, GUI에서 주변 문서를 탐색할 수 있게 합니다.
- MCP tools: 외부 agent가 wiki를 조회, 검색, 질의응답, raw scan, summarize, organize, lint할 수 있는 표준 tool interface입니다.
- Codex provider: `LLM_WIKI_AGENT_PROVIDER=codex`일 때 Codex CLI 로그인 세션을 사용해 answer/source/concept/review draft를 생성합니다. 실패하거나 schema가 맞지 않으면 rule-based 경로로 fallback합니다.
- desktop GUI: browser 기반 UI가 아니라 `tkinter` 데스크톱 앱입니다. raw scan, summarize, organize, lint 중심의 maintenance workflow와 graph 탐색, agent 질문을 제공합니다.

## 전체 동작 흐름

1. `domain.yml`로 도메인 이름, raw/wiki/manifest 경로, 기본 언어를 설정합니다.
2. 사용자가 `raw/` 폴더에 Markdown, PDF, HTML, 이미지 같은 자료를 추가합니다.
3. raw scan이 새 파일과 변경 파일을 `manifests/raw_sources.csv`에 기록합니다.
4. source summary 생성 단계가 raw source를 `wiki/sources/*.md`로 정리합니다.
5. quality review가 source가 usable인지, 수동 검토가 필요한지 판단합니다.
6. concept organize 단계가 usable source의 candidate concept를 `wiki/concepts/*.md`로 승격하거나 기존 concept와 병합합니다.
7. graph/lint 단계가 `wiki/graph/graph.json`을 생성하고 broken link, evidence 누락 같은 구조 문제를 점검합니다.
8. MCP server, desktop GUI, agent runtime이 같은 코어를 사용해 wiki 검색, 관련 문서 탐색, 근거 기반 답변, answer page 저장을 수행합니다.

## 빠른 실행

Python 3.11 이상 환경을 권장합니다.

```powershell
python -m pip install -r requirements.txt
```

Codex provider를 사용하려면 `.env.example`을 `.env`로 복사한 뒤 로컬 환경에 맞게 조정합니다. `.env`가 없어도 rule-based pipeline은 동작합니다.

```powershell
Copy-Item .env.example .env
```

예제 도메인 pipeline 실행:

```powershell
python scripts\wiki_tool.py --domain examples\finance\domain.yml pipeline
```

lint 실행:

```powershell
python scripts\lint_wiki.py --domain examples\finance\domain.yml
```

MCP server 실행:

```powershell
python scripts\run_mcp_server.py --domain examples\finance\domain.yml --transport stdio
```

desktop GUI 실행:

```powershell
python scripts\run_desktop_gui.py --domain examples\finance\domain.yml
```

Codex provider answer smoke 확인:

```powershell
python scripts\smoke_codex_provider.py --domain examples\finance\domain.yml --question "CAPM은 무엇인가?"
```

raw -> source -> concept smoke까지 포함하려면:

```powershell
python scripts\smoke_codex_provider.py --domain examples\finance\domain.yml --question "CAPM은 무엇인가?" --include-pipeline
```

## MCP tool 목록

| Tool | 역할 |
| --- | --- |
| `list_wiki_pages` | wiki page 목록을 page type별로 조회합니다. |
| `read_wiki_page` | 특정 wiki page Markdown을 읽습니다. |
| `search_wiki` | keyword 기반으로 wiki page를 검색합니다. |
| `get_wiki_graph` | Markdown link 기반 graph 데이터를 생성하고 반환합니다. |
| `get_related_pages` | graph에서 특정 page 주변 문서를 찾습니다. |
| `ask_wiki_context` | 질문에 관련된 wiki context와 주변 문서를 모읍니다. |
| `answer_question` | wiki evidence 기반으로 질문에 답합니다. Codex provider가 실패하면 rule-based fallback을 사용합니다. |
| `scan_raw_sources` | raw folder 변경점을 manifest에 기록합니다. |
| `summarize_new_sources` | `new` raw source를 source summary page로 생성합니다. |
| `organize_pending_sources` | summarized source를 concept page로 승격하거나 기존 concept에 병합합니다. |
| `draft_source_summary_with_agent` | agent provider를 통해 source summary draft를 생성합니다. |
| `draft_concept_update_with_agent` | agent provider를 통해 concept update draft를 생성합니다. |
| `review_wiki_changes_with_agent` | maintenance 변경 요약을 agent provider로 검토합니다. |
| `apply_wiki_update` | agent answer를 `wiki/answers/` page로 저장합니다. |
| `run_wiki_lint` | wiki 구조와 링크, evidence 상태를 점검합니다. |

## Codex provider 설정

Codex provider는 OpenAI API key 입력 UI를 제공하지 않습니다. 로컬 Codex CLI 로그인 세션과 `codex.cmd`를 사용합니다.

`.env.example`:

```text
LLM_WIKI_AGENT_PROVIDER=codex
LLM_WIKI_AGENT_MODEL=gpt-5.5
LLM_WIKI_ANSWER_MODEL=gpt-5.5
LLM_WIKI_INGEST_MODEL=gpt-5.5
LLM_WIKI_CONCEPT_MODEL=gpt-5.5
LLM_WIKI_REVIEW_MODEL=gpt-5.5
LLM_WIKI_CODEX_COMMAND=codex.cmd
```

- `LLM_WIKI_AGENT_PROVIDER`: `codex` 또는 기본 fallback인 `rule_based` 경로를 결정합니다.
- `LLM_WIKI_AGENT_MODEL`: role별 model 값이 없을 때 쓰는 기본 Codex model입니다.
- `LLM_WIKI_ANSWER_MODEL`: answer agent에 사용할 model입니다.
- `LLM_WIKI_INGEST_MODEL`: source summary draft에 사용할 model입니다.
- `LLM_WIKI_CONCEPT_MODEL`: concept update draft에 사용할 model입니다.
- `LLM_WIKI_REVIEW_MODEL`: maintenance review에 사용할 model입니다.
- `LLM_WIKI_CODEX_COMMAND`: 실행할 Codex CLI command입니다.

환경 변수가 이미 설정되어 있으면 `.env` 값은 덮어쓰지 않습니다.

## Public/private raw data 정책

공개 저장소에는 private raw 자료, 저작권 PDF 원본, 이미지 원본, HTML 원본, API key, local runtime state를 포함하지 않습니다.

- 실제 개인 자료는 로컬 `raw/` 또는 도메인별 `raw/`에 둘 수 있지만 커밋하지 않습니다.
- `raw/private/`와 `examples/**/raw/private/`는 스캔 및 공개 예제 경계 밖으로 취급합니다.
- `examples/**/raw/`에는 public-safe 텍스트 fixture만 둡니다.
- 공개 예제 wiki는 public-safe raw fixture에서 생성된 산출물만 포함합니다.

## 검증

```powershell
python -m unittest discover -v
python -m compileall scripts wiki_tool tests
python scripts\lint_wiki.py --domain examples\finance\domain.yml
```

Codex provider 실제 연결은 unit test가 아니라 smoke runner로 확인합니다.

```powershell
python scripts\smoke_codex_provider.py --domain examples\finance\domain.yml --question "CAPM은 무엇인가?"
```

## 현재 한계

- PDF나 image-heavy source는 텍스트 추출이 약하면 `needs_review`가 될 수 있습니다.
- vision 기반 이미지/PDF 분석은 현재 핵심 pipeline이 아니라 확장 경로입니다.
- 완전한 background job system은 아닙니다. `scripts\run_agent_runtime.py`는 반복 실행 루프를 제공하지만, 작업 큐와 retry dashboard를 갖춘 별도 job runner는 아닙니다.
- 검색은 현재 로컬 Markdown 기반 검색과 graph context 중심입니다. 별도 vector database는 포함하지 않습니다.
