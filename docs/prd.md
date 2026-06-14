# PRD 요약

구현 source of truth는 루트 [`prd.md`](../prd.md)입니다. 이 문서는 전체 PRD를 반복하지 않고, 현재 구현이 지키는 제품 목표와 acceptance 기준을 빠르게 확인하기 위한 entrypoint입니다.

## 제품 목표

LLM Wiki Tool v2는 사용자가 정의한 지식 도메인의 raw 자료를 Markdown 기반 wiki로 유지보수하는 도구입니다. raw source를 source summary page로 정리하고, source evidence를 바탕으로 concept page를 승격 또는 병합하며, MCP tools와 desktop GUI를 통해 agent가 검색, 답변, 검토, 저장, maintenance를 수행할 수 있게 합니다.

## 핵심 원칙

- `raw/`는 불변 원본 계층입니다.
- `wiki/`는 source, concept, answer, graph, navigation 산출물을 담는 compiled knowledge layer입니다.
- raw source는 바로 concept page가 되지 않고 source summary page를 먼저 거칩니다.
- concept page는 source evidence 기반이어야 합니다.
- weak source는 자동 promotion하지 않고 `needs_review`로 남깁니다.
- answer page는 evidence-backed answer만 저장합니다.
- answer-derived concept update는 source evidence가 있는 draft만 append-only 방식으로 반영합니다.
- 한국어 사용자-facing 출력은 한국어를 기본으로 합니다.
- public repo에는 private raw, 저작권 원본, API key, local runtime state를 포함하지 않습니다.
- GUI의 primary ingest UX는 upload가 아니라 raw scan, summarize, organize, lint, maintenance workflow입니다.
- MCP server는 agent와 wiki 사이의 표준 tool interface입니다.

## Acceptance Criteria 요약

- 사용자가 `domain.yml`과 `raw/`를 바꾸면 다른 도메인에도 같은 pipeline을 적용할 수 있습니다.
- `user_domains/<slug>/` 아래 개인 도메인은 Git ignore되는 runtime data로 관리할 수 있습니다.
- raw scan은 raw 파일을 수정하지 않고 manifest에 path, hash, status를 기록합니다.
- source summary page는 `Summary`, `Key Points`, `Evidence`, `Candidate Concepts`, `Quality Review`를 포함합니다.
- concept organizer는 근거가 있는 candidate concept만 승격하고, 기존 concept와 겹치면 병합합니다.
- graph/navigation refresh는 `graph.json`, `index.md`, `overview.md`, `log.md`를 최신 상태로 유지합니다.
- MCP tool은 wiki 조회, 검색, graph, related page, answer, raw scan, summarize, organize, answer maintenance, lint를 제공해야 합니다.
- Codex provider 사용 시 실패나 schema mismatch가 있어도 rule-based fallback이 동작해야 합니다.
- Gemini provider는 skeleton 단계임을 명확히 표시하고, 실제 role 연결처럼 문서화하지 않습니다.
- PySide6 desktop GUI는 3분할 화면에서 유지보수 흐름, graphify 탐색, MCP-first agent route, chat log, provider status를 한국어로 이해 가능하게 보여주고, 긴 agent/maintenance 작업 중에도 event loop를 막지 않아야 합니다.
- 저장된 answer page는 maintenance 후보로 분석되며, source evidence가 있는 기존 concept match만 `## Answer-Derived Notes`에 중복 없이 append됩니다.
- maintenance report와 `log.md`는 answer-derived concept update의 applied/skipped/reason 요약을 보여줘야 합니다.

## Non-goals

- browser-based GUI를 primary GUI로 만들지 않습니다.
- GUI file upload/dropzone을 primary ingest path로 만들지 않습니다.
- OpenAI API key 입력 UI를 구현하지 않습니다.
- raw/PDF/image 원본을 public repo에 포함하지 않습니다.
- 모든 answer를 무조건 저장하지 않습니다.
- answer-derived draft만으로 새 concept page를 자동 생성하지 않습니다.
- concept page 본문을 통째로 덮어쓰지 않습니다.
- Gemini answer/review/ingest/concept role 연결은 현재 단계의 구현 범위가 아닙니다.
- 완전한 background job queue나 vector database를 필수 구성요소로 두지 않습니다.
- vision 기반 PDF/image 분석은 현재 core acceptance가 아니라 확장 경로입니다.

자세한 schema, 흐름, 품질 기준, 언어 정책은 루트 [`prd.md`](../prd.md)를 기준으로 확인하세요.
