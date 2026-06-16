# LLM Wiki Tool v2

LLM Wiki Tool v2는 사용자가 직접 만든 지식 도메인의 자료를 Markdown wiki로 정리하고, MCP tools와 PySide6 데스크톱 GUI를 통해 검색, 답변, 유지보수를 수행하는 로컬 위키 하네스입니다.

이 프로젝트는 금융투자론 전용 도구가 아닙니다. `examples/finance`는 public-safe 샘플 도메인일 뿐이고, 실제 사용자는 `user_domains/<slug>/` 아래에 자기 도메인을 만들고 `raw/`에 자료를 넣어 위키를 관리합니다.

핵심 경계는 단순합니다.

- `raw/`: immutable source layer입니다. 앱, CLI, MCP tool, agent는 raw 파일을 수정, 이동, 삭제하지 않습니다.
- `wiki/`: compiled knowledge layer입니다. source summary, concept page, answer page, graph, index, overview, log가 생성됩니다.
- `manifests/`: raw scan 상태와 source 처리 상태를 기록합니다.

## 주요 개념

- Source Summary Page: raw 자료 하나를 `Summary`, `Key Points`, `Evidence`, `Candidate Concepts`, `Quality Review` 구조로 정리한 source 문서입니다.
- Concept Page: source evidence를 바탕으로 만들어지는 durable wiki page입니다. 기존 concept와 겹치면 새 문서를 계속 만들기보다 병합합니다.
- Graphify: Markdown link와 source evidence 관계를 `wiki/graph/graph.json`으로 만들고 GUI에서 주변 문서를 탐색합니다.
- Answer Page: agent answer 중 policy상 저장 가능한 답변만 `wiki/answers/`에 저장합니다.
- Answer-Derived Notes: source evidence가 있는 저장 답변에서 concept update draft를 만들고, maintenance workflow가 승인 가능한 기존 concept에만 `## Answer-Derived Notes`로 append합니다.
- MCP Tools: agent가 파일 구조를 직접 추측하지 않고 wiki 조회, 검색, 답변, 유지보수를 호출하는 표준 인터페이스입니다.

## 전체 동작 흐름

1. `domain.yml`로 도메인 이름, slug, raw/wiki/manifest 경로, 기본 언어를 정의합니다.
2. 사용자가 `raw/`에 Markdown, PDF, HTML 같은 자료를 추가합니다.
3. `scan_raw_sources`가 raw 변경점을 manifest에 기록합니다.
4. `summarize_new_sources`가 새 raw 자료를 `wiki/sources/*.md` source summary page로 컴파일합니다.
5. `organize_pending_sources`가 usable source의 candidate concept를 `wiki/concepts/*.md`로 승격하거나 병합합니다.
6. navigation과 graph 갱신으로 `index.md`, `overview.md`, `log.md`, `graph.json`이 최신 상태를 반영합니다.
7. `run_wiki_lint`가 링크, evidence, wiki 구조 문제를 점검합니다.
8. GUI나 MCP agent가 wiki evidence 기반으로 질문에 답합니다.
9. 저장 가능한 answer는 자동으로 `wiki/answers/`에 저장되고, 이후 maintenance workflow에서 concept 반영 후보로 분석됩니다.
10. source evidence가 있는 answer-derived draft만 기존 concept의 `## Answer-Derived Notes`에 append됩니다. 같은 answer는 marker로 중복 반영을 막습니다.

## 빠른 실행

Python 3.11 이상을 권장합니다.

```powershell
python -m pip install -r requirements.txt
```

처음 실행할 때 `.env`는 선택 사항입니다. 별도 설정이 없으면 앱은 사용 가능한 CLI provider를 `codex.cmd` -> `codex` -> `gemini.cmd` -> `gemini` -> `rule_based` 순서로 자동 탐지합니다. 고급 사용자만 `.env.example`을 `.env`로 복사해 provider, model, command를 직접 override하면 됩니다.

```powershell
# 필요할 때만 생성
Copy-Item .env.example .env
```

사용자 도메인 생성:

```powershell
python scripts\init_user_domain.py --slug finance-private --name "내 금융 위키"
```

생성된 도메인에 raw 자료를 넣습니다.

```text
user_domains/
  finance-private/
    domain.yml
    raw/
```

PySide6 desktop GUI 실행:

```powershell
setup.bat
run_app.bat
```

macOS/Linux:

```bash
chmod +x setup.sh run_app.sh
./setup.sh
./run_app.sh
```

`run_app.bat`과 `run_app.sh`는 repo-local `.venv`의 Python을 사용합니다. clone 후 처음 실행할 때는 먼저 `setup.bat` 또는 `./setup.sh`로 가상환경과 의존성을 준비하세요.

직접 Python launcher를 실행해 domain을 지정할 수도 있습니다.

```powershell
python scripts\run_app.py --domain user_domains\finance-private\domain.yml
```

GUI를 띄우기 전에 domain/provider/PySide6 상태만 확인하려면:

```powershell
python scripts\run_app.py --check
```

기존 GUI 진입점도 유지됩니다.

```powershell
python scripts\run_desktop_gui.py --domain user_domains\finance-private\domain.yml
```

샘플 도메인으로 GUI를 실행하려면:

```powershell
python scripts\run_desktop_gui.py --domain examples\finance\domain.yml
```

CLI pipeline 실행:

```powershell
python scripts\wiki_tool.py --domain examples\finance\domain.yml pipeline
```

agent maintenance runtime을 한 번 실행:

```powershell
python scripts\run_agent_runtime.py --domain examples\finance\domain.yml --once
```

lint 실행:

```powershell
python scripts\lint_wiki.py --domain examples\finance\domain.yml
```

MCP server 실행:

```powershell
python scripts\run_mcp_server.py --domain examples\finance\domain.yml --transport stdio --toolset readonly
```

GUI와 MCP server는 실행 목적이 다릅니다. GUI는 내부 wiki core를 직접 호출하는 데스크톱 클라이언트이고, MCP server는 Codex 같은 외부 agent가 같은 wiki 기능을 tool로 호출하기 위한 stdio server입니다. stdio MCP server는 사용자가 미리 켜두는 상시 서버가 아니라, MCP client에 등록된 command가 필요할 때 실행하는 방식입니다.

MCP server의 기본 toolset은 `readonly`입니다. 외부 agent 연결에서는 wiki page 목록, 읽기, 검색, graph/context, lint 같은 가벼운 read-only/context 도구만 노출하고, 실제 답변 생성은 외부 Codex agent가 담당하는 구조를 권장합니다. raw ingest, source summary, concept organize, answer 저장, review 같은 무거운 생성/수정 도구는 GUI의 maintenance workflow에서 실행하세요. 외부 MCP client에 maintenance/update 도구까지 의도적으로 노출해야 할 때만 `--toolset full`을 사용합니다.

Codex MCP client 등록 예시:

```powershell
codex mcp add llm-wiki -- python scripts\run_mcp_server.py --domain examples\finance\domain.yml --transport stdio --toolset readonly
```

setup wrapper로 만든 `.venv`를 명시하려면:

```powershell
codex mcp add llm-wiki -- .venv\Scripts\python.exe scripts\run_mcp_server.py --domain examples\finance\domain.yml --transport stdio --toolset readonly
```

macOS/Linux:

```bash
codex mcp add llm-wiki -- python3 scripts/run_mcp_server.py --domain examples/finance/domain.yml --transport stdio --toolset readonly
```

`.venv` Python을 명시하려면:

```bash
codex mcp add llm-wiki -- .venv/bin/python scripts/run_mcp_server.py --domain examples/finance/domain.yml --transport stdio --toolset readonly
```

완성된 wiki를 포함해 배포받은 사용자는 raw ingest를 다시 실행하지 않아도 MCP server를 통해 읽기, 검색, context tool을 사용할 수 있습니다.

Codex MCP 등록 예시는 사용하는 MCP host 설정 형식에 맞춰 아래 command/args를 넣으면 됩니다.

```json
{
  "mcpServers": {
    "llm-wiki-finance": {
      "command": "python",
      "args": [
        "scripts\\run_mcp_server.py",
        "--domain",
        "examples\\finance\\domain.yml",
        "--transport",
        "stdio",
        "--toolset",
        "readonly"
      ]
    }
  }
}
```

Codex provider smoke 확인:

```powershell
python scripts\smoke_codex_provider.py --domain examples\finance\domain.yml --question "CAPM은 무엇인가?"
```

raw -> source -> concept smoke까지 확인하려면:

```powershell
python scripts\smoke_codex_provider.py --domain examples\finance\domain.yml --question "CAPM은 무엇인가?" --include-pipeline
```

Gemini answer provider smoke 확인:

```powershell
$env:LLM_WIKI_ANSWER_PROVIDER="gemini"
python scripts\smoke_answer_provider.py --domain examples\finance\domain.yml --question "CAPM은 무엇인가?" --provider gemini --ignore-dotenv
```

`--provider gemini`로 answer provider를 강제했는데 Gemini CLI가 없거나 Gemini 호출이 실패해 `rule_based` fallback으로 내려가면 smoke runner는 non-zero exit code를 반환합니다. `--provider auto`에서 fallback이 정상 동작하면 fallback 검증 성공으로 보고 exit code 0을 반환합니다. `--ignore-dotenv`를 붙이면 repo의 `.env`를 읽지 않아, 기존 `LLM_WIKI_*_MODEL` override가 Gemini smoke에 섞이는 일을 피할 수 있습니다.

Gemini ingest provider smoke 확인:

```powershell
$env:LLM_WIKI_INGEST_PROVIDER="gemini"
python scripts\smoke_gemini_ingest.py --ignore-dotenv
```

Gemini ingest smoke는 실행 중 `LLM_WIKI_INGEST_PROVIDER=gemini`을 우선 적용합니다. Gemini CLI가 없거나 source summary 생성이 fallback으로 내려가면 non-zero exit code를 반환합니다. 이 smoke는 임시 public-safe domain을 사용하므로 `examples/finance/wiki` 산출물을 수정하지 않습니다.

Gemini concept provider smoke 확인:

```powershell
$env:LLM_WIKI_CONCEPT_PROVIDER="gemini"
python scripts\smoke_gemini_concept.py --ignore-dotenv
```

Gemini concept smoke는 실행 중 `LLM_WIKI_CONCEPT_PROVIDER=gemini`을 우선 적용하고 source 생성 단계는 deterministic fallback으로 격리합니다. Gemini CLI가 없거나 concept draft가 fallback으로 내려가면 non-zero exit code를 반환합니다. 이 smoke도 임시 public-safe domain을 사용하므로 `examples/finance/wiki` 산출물을 수정하지 않습니다.

Gemini model candidate matrix smoke 확인:

```powershell
python scripts\smoke_gemini_model_matrix.py --ignore-dotenv
python scripts\smoke_gemini_model_matrix.py --role ingest --model gemini-2.5-flash --model gemini-3-flash-preview --model gemini-3.1-flash-lite-preview --ignore-dotenv
```

이 matrix smoke는 ingest, concept, answer role에 대해 Gemini model id 후보를 임시 smoke 경로로 검증합니다. 로컬 Gemini CLI가 model list를 제공하지 않는 환경에서는 후보 id를 추측하지 말고 `--model`로 실제 후보를 넘겨 row별 PASS/FAIL을 확인하세요. invalid model id는 해당 row만 FAIL로 표시되고 전체 비교는 계속 진행됩니다.

## Desktop GUI

GUI는 browser UI가 아니라 PySide6 기반 3분할 데스크톱 앱입니다.

- 왼쪽: 도메인 선택, 새 사용자 도메인 생성, raw 폴더 열기, wiki page 목록과 검색
- 중앙: 선택한 Markdown wiki page 본문과 관계 그래프
- 오른쪽: Wiki Agent chat, provider/model 상태, 위키 업데이트 버튼, 고급 maintenance controls

오른쪽 Wiki Agent는 MCP tool registry를 우선 route로 사용합니다. GUI에는 `agent route: mcp/codex`, `agent route: mcp/gemini`, `agent route: mcp/rule_based`, `agent route: direct fallback`처럼 현재 답변 경로가 표시됩니다. agent 질문과 maintenance 계열 작업은 background worker에서 실행되어 긴 작업 중에도 창이 멈추지 않도록 구성되어 있습니다.

일반 사용자는 `위키 업데이트` 버튼 하나로 raw scan, source summary, concept organize, answer-derived concept update, graph/navigation refresh, lint를 실행할 수 있습니다. 세부 작업 버튼은 `고급 관리` 영역에 접어 둡니다.

## MCP Tool 목록

기본 MCP server는 `--toolset readonly`로 실행되며 다음 read-only/context 도구만 노출합니다: `list_wiki_pages`, `read_wiki_page`, `search_wiki`, `get_wiki_graph`, `get_related_pages`, `ask_wiki_context`, `run_wiki_lint`. 아래 전체 도구 목록은 `--toolset full`을 명시했을 때 외부 MCP client에 노출할 수 있는 maintenance/update 도구까지 포함합니다.

| Tool | 역할 |
| --- | --- |
| `list_wiki_pages` | wiki page 목록을 조회합니다. |
| `read_wiki_page` | 특정 wiki page Markdown을 읽습니다. |
| `search_wiki` | keyword 기반으로 wiki page를 검색합니다. |
| `get_wiki_graph` | `wiki/graph/graph.json`을 생성하고 graph 데이터를 반환합니다. |
| `get_related_pages` | graph에서 특정 page 주변 문서를 찾습니다. |
| `ask_wiki_context` | 질문에 관련된 wiki context packet을 반환합니다. |
| `answer_question` | wiki evidence 기반으로 질문에 답하고 save decision을 포함합니다. |
| `scan_raw_sources` | raw folder 변경점을 manifest에 기록합니다. |
| `summarize_new_sources` | 새 raw source를 source summary page로 생성합니다. |
| `organize_pending_sources` | pending source를 concept page로 승격/병합합니다. |
| `analyze_answer_candidates` | 저장된 answer page를 concept 반영 후보로 분석합니다. |
| `draft_answer_concept_updates` | answer 후보에서 concept update draft를 생성합니다. |
| `apply_answer_concept_updates` | source-backed draft만 기존 concept의 `Answer-Derived Notes`에 append합니다. |
| `draft_source_summary_with_agent` | agent provider로 source summary draft를 생성합니다. |
| `draft_concept_update_with_agent` | agent provider로 concept update draft를 생성합니다. |
| `review_wiki_changes_with_agent` | maintenance 변경 요약을 agent provider로 검토합니다. |
| `apply_wiki_update` | 저장 가능한 answer를 `wiki/answers/`에 생성 또는 업데이트합니다. |
| `run_wiki_lint` | wiki 구조, 링크, evidence 상태를 점검합니다. |

## Agent Provider 구조

현재 우선 지원 provider는 Codex CLI입니다. `.env`가 없어도 실행 시 로컬 CLI를 자동 탐지하며, Codex CLI가 사용 가능하면 Codex를 먼저 사용하고 Codex가 없으면 Gemini CLI를 시도한 뒤 둘 다 없으면 `rule_based` fallback을 사용합니다. OpenAI API key 입력 UI를 만들지 않고, 사용자가 이미 로그인해 둔 로컬 CLI 세션을 subprocess로 호출합니다.

자동 탐지 순서:

1. `codex.cmd`
2. `codex`
3. `gemini.cmd`
4. `gemini`
5. `rule_based` fallback

- `codex`: answer, ingest, concept, review role에 연결되어 있습니다.
- `gemini`: answer, ingest, concept, review role에 연결되어 있습니다.
- `rule_based`: 항상 사용 가능한 deterministic fallback입니다.
- `claude`: 현재 provider 목록에서 제외되어 있습니다.

`.env`는 필수가 아니라 고급 사용자용 override 파일입니다. 필요한 줄만 `.env.example`에서 주석을 풀어 사용하세요.

```text
# Codex를 명시적으로 고정
# LLM_WIKI_AGENT_PROVIDER=codex

# Gemini를 특정 role에만 사용
# LLM_WIKI_ANSWER_PROVIDER=gemini
# LLM_WIKI_INGEST_PROVIDER=gemini

# Windows command override
# LLM_WIKI_CODEX_COMMAND=codex.cmd
# LLM_WIKI_GEMINI_COMMAND=gemini.cmd

# Gemini model override 예시
# LLM_WIKI_ANSWER_MODEL=gemini-2.5-flash
```

주요 환경 변수:

- `LLM_WIKI_AGENT_PROVIDER`: 전역 provider입니다. 예: `codex`, `gemini`, `rule_based`
- `LLM_WIKI_ANSWER_PROVIDER`, `LLM_WIKI_INGEST_PROVIDER`, `LLM_WIKI_CONCEPT_PROVIDER`, `LLM_WIKI_REVIEW_PROVIDER`: role별 provider override입니다.
- `LLM_WIKI_AGENT_MODEL`: role별 model이 없을 때 쓰는 기본 model입니다. 설정하지 않으면 Codex는 CLI 기본 모델을 사용하고, Gemini는 `gemini-2.5-flash`를 사용합니다.
- `LLM_WIKI_ANSWER_MODEL`, `LLM_WIKI_INGEST_MODEL`, `LLM_WIKI_CONCEPT_MODEL`, `LLM_WIKI_REVIEW_MODEL`: role별 model입니다.
- `LLM_WIKI_CODEX_COMMAND`: Codex CLI command입니다. 설정하지 않으면 Windows wrapper인 `codex.cmd`와 bare command인 `codex`를 순서대로 탐지합니다.
- `LLM_WIKI_GEMINI_COMMAND`: Gemini CLI 감지 및 answer/ingest/concept/review 호출용 command입니다. 설정하지 않으면 Windows wrapper인 `gemini.cmd`와 bare command인 `gemini`를 순서대로 탐지합니다.

이미 OS 환경 변수에 값이 있으면 `.env` 값은 덮어쓰지 않습니다.

Codex와 Gemini의 모델명은 서로 호환되지 않습니다. Gemini provider를 사용할 때 `gpt-*` 모델명을 넣지 말고, 기본값인 `gemini-2.5-flash` 또는 Gemini CLI에서 지원하는 모델명을 사용하세요.

Gemini CLI 사용 가능 여부, 인증 방식, 비용과 쿼터는 Google 계정과 Gemini CLI 정책에 따라 달라질 수 있습니다.

## Answer 저장과 Answer-Derived Concept Update

`answer_question` 결과에는 deterministic save decision이 붙습니다. 저장 대상은 다음 조건을 만족해야 합니다.

- answer status가 `ok`
- fallback 답변이 아님
- answer 본문이 비어 있지 않음
- evidence 또는 used pages가 있음
- `no_evidence` 상태가 아님

저장 가능한 답변은 GUI agent workflow에서 자동으로 `wiki/answers/`에 저장됩니다. 같은 질문 또는 suggested title은 같은 answer page를 업데이트하므로 파일이 계속 늘어나지 않습니다. 저장 후 `index.md`, `overview.md`, `log.md`, `graph.json`도 갱신됩니다.

maintenance workflow는 저장된 answer page를 분석해 concept update draft를 만듭니다. 단, 실제 concept 반영은 source evidence가 있는 draft만 대상입니다. 적용은 기존 concept page의 `## Answer-Derived Notes` 아래 append 방식으로만 이루어지고, marker를 사용해 같은 answer가 중복 반영되지 않게 합니다. report와 `log.md`에는 applied/skipped count, 대표 경로, skip reason 요약이 남습니다.

## Public / Private Data 정책

공개 저장소에는 직접 작성한 샘플 raw와 public-safe 예제 산출물만 포함합니다.

- 개인 강의자료, PDF 원본, 유료 자료, 저작권 자료, 이미지 원본, HTML 원본, API key, local runtime state는 public repo에 올리지 않습니다.
- `examples/`는 public sample과 테스트 fixture용입니다.
- 실제 사용자는 `user_domains/<slug>/` 아래에 개인 도메인을 만들고 raw/wiki/manifest를 관리합니다.
- `user_domains/<slug>/` 하위의 `domain.yml`, `raw/`, `wiki/`, `manifests/`는 Git ignore 대상입니다.
- 민감한 자료가 있다면 public sample이 아니라 private domain이나 `raw/private/` 경계를 사용하세요.

## 검증 명령

```powershell
python -m unittest discover -v
python -m compileall scripts wiki_tool tests
python scripts\lint_wiki.py --domain examples\finance\domain.yml
```

Codex CLI 실제 연결은 unit test가 아니라 smoke runner로 확인합니다.

```powershell
python scripts\smoke_codex_provider.py --domain examples\finance\domain.yml --question "CAPM은 무엇인가?"
```

## 현재 한계

- PDF나 image-heavy source는 텍스트 추출이 약하면 `needs_review`가 될 수 있습니다.
- vision 기반 PDF/image 분석은 현재 core pipeline이 아니라 확장 경로입니다.
- 완전한 background job system은 아닙니다. `scripts\run_agent_runtime.py`는 반복 실행을 제공하지만, 별도 queue/retry dashboard는 없습니다.
- 검색은 로컬 Markdown 검색과 graph context 중심입니다. 별도 vector database는 포함하지 않습니다.
- Gemini provider는 answer, ingest, concept, review role에 연결되어 있습니다.
