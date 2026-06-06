# Agent Spec

이 문서는 LLM Wiki Tool v2에서 agent 역할과 권한 경계를 정리합니다. Codex provider를 사용하더라도 같은 권한 정책이 적용됩니다.

## 공통 권한 원칙

- 모든 agent는 `raw/` 파일을 수정, 이동, 삭제, 재작성하면 안 됩니다.
- raw source는 읽기 전용 evidence source입니다.
- 생성물은 `manifest`, `wiki/sources`, `wiki/concepts`, `wiki/answers`, `wiki/graph`, `wiki/log.md` 같은 생성 계층에만 기록합니다.
- private raw, API key, local runtime state를 wiki 본문이나 public 예제 산출물에 노출하지 않습니다.
- 근거가 부족하면 추측하지 않고 `needs_review` 또는 `no_evidence` 상태를 명확히 남깁니다.

## Raw Scanner Agent

역할:

- `raw_dir` 아래 public-safe source를 스캔합니다.
- 파일 path, sha256, source_type, status를 manifest에 기록합니다.
- 변경된 raw file을 재처리 대상으로 표시합니다.

읽기 가능:

- `domain.yml`
- `raw_dir` 파일 metadata와 content hash
- 기존 manifest

쓰기 가능:

- `manifest`

금지:

- raw 파일 수정, 이동, 삭제
- `raw/private/`를 public ingest 대상으로 처리

## Source Summarizer Agent

역할:

- `new` 또는 재처리 대상 raw source를 source summary page로 변환합니다.
- `Summary`, `Key Points`, `Evidence`, `Candidate Concepts`, `Quality Review`를 구성합니다.
- candidate concept가 명사구인지 정제하고, 문장 조각을 제거합니다.

읽기 가능:

- raw source content
- manifest
- domain language policy

쓰기 가능:

- `wiki/sources/*.md`
- manifest status와 source_page 경로

금지:

- raw extraction dump를 reader-facing 본문에 과도하게 노출
- weak source를 usable처럼 위장
- raw 파일 수정

Codex provider:

- `LLM_WIKI_AGENT_PROVIDER=codex`이면 Codex source draft를 사용할 수 있습니다.
- draft가 필수 section을 만족하지 않으면 rule-based source summary로 fallback합니다.

## Quality Review Agent

역할:

- source text, extraction warning, candidate concept, evidence 상태를 검토합니다.
- usable source와 `needs_review` source를 구분합니다.
- PDF/image-heavy source처럼 정보가 부족한 경우 보완 action을 남깁니다.

읽기 가능:

- extracted source text
- source warnings
- candidate concept와 evidence

쓰기 가능:

- source page의 `Quality Review`
- manifest status

금지:

- 근거 부족 source를 concept promotion 대상으로 통과시키기
- 사용자에게 필요한 보완 조치를 숨기기

## Concept Organizer Agent

역할:

- summarized source의 candidate concept를 concept page로 승격하거나 기존 concept와 병합합니다.
- alias, slug, normalized title 기준으로 중복 concept 생성을 줄입니다.
- source evidence와 source link를 concept page에 유지합니다.

읽기 가능:

- `wiki/sources/*.md`
- 기존 `wiki/concepts/*.md`
- manifest

쓰기 가능:

- `wiki/concepts/*.md`
- manifest status
- `wiki/graph/graph.json`

금지:

- 사람이 작성한 기존 concept 본문을 덮어쓰기
- evidence 없는 candidate concept를 승격하기
- 문장 조각 후보를 concept title이나 graph node로 만들기
- raw 파일 수정

Codex provider:

- Codex concept draft가 valid하면 새 concept 생성이나 병합에 반영할 수 있습니다.
- draft가 invalid하면 rule-based organizer로 fallback합니다.
- 기존 사람이 작성한 reader-facing 내용은 유지해야 합니다.

## Retriever Agent

역할:

- 질문과 관련된 wiki page, source evidence, related page를 찾습니다.
- answer agent에 짧고 관련도 높은 context를 제공합니다.

읽기 가능:

- `wiki/sources`
- `wiki/concepts`
- `wiki/answers`
- `wiki/graph/graph.json`

쓰기 가능:

- 없음

금지:

- frontmatter, raw extraction block, maintenance metadata를 answer evidence처럼 섞기
- 근거가 약한 문서를 과도하게 확장해서 제공하기

## Answer Agent

역할:

- wiki evidence를 바탕으로 사용자의 질문에 답합니다.
- 근거가 부족하면 `no_evidence`로 응답합니다.
- 사용한 page와 related page를 answer 본문과 분리된 보조 데이터로 유지합니다.

읽기 가능:

- Retriever Agent가 제공한 wiki context
- 필요한 wiki page content

쓰기 가능:

- 직접 쓰기 없음
- `apply_wiki_update` tool 호출 시 `wiki/answers/*.md`

금지:

- wiki evidence 없이 추측 답변 생성
- metadata, raw extraction block, maintenance note를 답변 본문에 섞기
- private raw 내용을 노출하기

Codex provider:

- Codex answer가 valid하고 evidence가 있으면 사용합니다.
- Codex 실패, timeout, invalid answer, evidence 부족은 rule-based fallback으로 처리합니다.

Desktop GUI route:

- PySide6 desktop GUI의 Wiki Agent 패널은 MCP tool registry의 `answer_question`을 우선 호출합니다.
- GUI에는 `agent route: mcp/codex`, `agent route: mcp/rule_based`, `agent route: direct fallback` 형태로 실제 답변 경로를 표시합니다.
- MCP route가 실패한 경우에만 direct `WikiToolAdapter.answer_question()` fallback을 사용합니다.
- 에이전트 질문은 GUI event loop를 막지 않도록 background worker에서 실행하고, 완료 후 메인 스레드에서 출력과 route label을 갱신합니다.

## Maintenance/Review Agent

역할:

- raw scan, summarize, organize, graph, lint 결과를 검토합니다.
- Codex provider가 pipeline에서 사용된 경우 짧은 review를 남길 수 있습니다.
- GUI와 runtime에 maintenance run 결과를 요약합니다.
- PySide6 GUI의 maintenance 계열 작업은 background worker에서 실행하고, 완료 후 결과와 필요한 page list를 갱신합니다.

읽기 가능:

- scan/summarize/organize/lint 결과
- wiki graph와 lint issue
- source/concept 변경 요약

쓰기 가능:

- `wiki/log.md`
- maintenance note

금지:

- review 실패를 전체 pipeline 실패로 확대하기
- 긴 raw prompt나 Codex raw output을 GUI에 노출하기
- raw 파일 수정
