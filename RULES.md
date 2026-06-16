# LLM Wiki Harness Rules

이 문서는 LLM Wiki Tool v2를 다루는 사람과 agent가 공통으로 따르는 운영 지침입니다. 프로젝트의 목표는 사용자가 자기 도메인 자료를 `raw/`에 넣고, 로컬 CLI provider와 maintenance workflow를 통해 Markdown wiki를 생성하고 검증하는 것입니다.

## Core Boundaries

- `raw/`는 immutable source layer입니다. agent, GUI, MCP tool, maintenance script는 raw 파일을 수정, 이동, 삭제하지 않습니다.
- `wiki/`는 compiled knowledge layer입니다. source page, concept page, answer page, graph, index, overview, log는 재생성되거나 업데이트될 수 있습니다.
- `user_domains/<slug>/` 아래의 개인 domain, raw 자료, 생성 wiki 산출물은 Git에 올리지 않습니다.
- public repo에는 직접 작성한 public-safe sample raw와 제출에 필요한 demo asset만 둡니다.
- generated output을 commit할 때는 의도된 sample fixture인지 먼저 확인합니다.

## Evidence Policy

- 답변과 concept update는 wiki evidence를 기준으로 작성합니다.
- source page 또는 source evidence가 없는 answer-derived draft는 concept page에 반영하지 않습니다.
- fallback, no_evidence, provider failure 답변은 자동 저장 또는 concept 반영 대상으로 취급하지 않습니다.
- 저장된 answer page는 같은 질문의 이전 답변과 evidence를 재사용할 수 있지만, source evidence를 대체하는 최종 근거처럼 취급하지 않습니다.
- 기존 concept 본문을 통째로 덮어쓰지 않습니다. 자동 반영은 `## Answer-Derived Notes` 같은 명확한 section에 append하거나 section 단위로 merge합니다.

## Provider Policy

- 앱 안에 API key를 직접 넣지 않습니다.
- Codex, Gemini 같은 CLI provider는 사용자가 로컬에서 로그인해 둔 CLI를 subprocess로 호출합니다.
- provider/model은 자동 감지하되, `.env` 또는 환경 변수로 override할 수 있습니다.
- Codex CLI가 있으면 우선 사용하고, 없으면 Gemini CLI, 둘 다 없으면 `rule_based` fallback으로 동작합니다.
- Gemini 기본 모델은 `gemini-2.5-flash`입니다. 품질이 중요한 작업은 provider/model override를 검토합니다.
- provider 실패가 발생해도 maintenance 전체가 중단되지 않도록 fallback 또는 skip result를 명확히 남깁니다.

## Maintenance Policy

- 일반 사용자는 GUI의 `위키 업데이트`로 raw scan, source summary, concept organize, answer-derived concept update, graph/navigation refresh, lint를 실행합니다.
- source/concept/answer page가 변경되면 graph, index, overview, log도 함께 갱신되어야 합니다.
- maintenance report는 applied/skipped/reason을 짧게 보여주고, 긴 세부 결과는 wiki/log.md에 추적 가능하게 남깁니다.
- 같은 answer-derived draft는 idempotency marker로 중복 반영하지 않습니다.
- lint 실패는 숨기지 말고 report/status에 표시합니다.

## MCP Policy

- 외부 agent용 MCP server의 기본 toolset은 `readonly`입니다.
- 기본 MCP toolset은 list/read/search/graph/context/lint 같은 가벼운 도구만 노출합니다.
- raw ingest, source summary, concept organize, answer 저장, review 같은 무거운 도구는 GUI 또는 maintenance workflow에서 실행하는 것을 기본으로 합니다.
- 외부 MCP client에 생성/수정 도구를 노출해야 할 때만 `--toolset full`을 명시합니다.

## Git And Packaging Policy

- `.env`, 개인 raw 자료, `user_domains/<slug>/` 하위 자료는 commit하지 않습니다.
- `examples/finance/wiki/*`, `examples/finance/manifests/*`, graph output은 의도된 sample update가 아니면 stage하지 않습니다.
- commit 전에는 `git status --short --branch`로 generated output과 private data가 섞이지 않았는지 확인합니다.
- 검증은 가능한 좁은 테스트부터 실행하고, 제출 전에는 `python -m unittest discover -v`, `python -m compileall scripts wiki_tool tests`, `python scripts\lint_wiki.py --domain examples\finance\domain.yml`를 확인합니다.
