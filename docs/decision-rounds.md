# Decision Rounds

이 문서는 v2 구현에서 반복적으로 흔들릴 수 있는 선택지를 고정해 둔 기록입니다. 세부 요구사항의 source of truth는 루트 `prd.md`이며, 이 문서는 구현 방향을 빠르게 이해하기 위한 보조 문서입니다.

## raw folder 기반 ingest

v2의 primary ingest path는 GUI upload/dropzone이 아니라 `raw/` 폴더입니다.

결정 이유:

- 사용자가 원본 파일의 위치와 변경 이력을 직접 통제할 수 있습니다.
- agent, MCP tool, desktop GUI, CLI가 같은 filesystem contract를 공유합니다.
- public/private raw 경계를 명확히 유지할 수 있습니다.

따라서 desktop GUI는 파일 업로드 앱처럼 동작하지 않습니다. GUI는 raw scan, summarize, organize, lint를 실행하고 결과를 보여주는 maintenance surface입니다.

## source summary -> concept page 2단계

raw source를 곧바로 concept page로 만들지 않습니다.

결정 이유:

- raw source는 문서, PDF 추출 텍스트, HTML 본문, 이미지 설명처럼 품질과 구조가 제각각입니다.
- source summary page가 provenance, evidence, candidate concept, quality review를 먼저 정리해야 concept page 병합이 안전합니다.
- concept page는 durable knowledge page이므로 source evidence 없이 생성되면 안 됩니다.

현재 pipeline은 `raw -> wiki/sources/*.md -> wiki/concepts/*.md` 순서를 따릅니다.

## weak source는 needs_review로 차단

텍스트가 부족하거나 PDF/image-heavy source처럼 extraction confidence가 낮은 source는 자동 concept promotion을 하지 않습니다.

결정 이유:

- 품질이 낮은 source를 억지로 concept page로 승격하면 wiki 전체가 오염됩니다.
- 사용자가 OCR, vision, 수동 요약 같은 보완 작업을 해야 할 지점을 명확히 볼 수 있습니다.

`needs_review`는 실패가 아니라 안전장치입니다.

## Codex CLI provider

rule-based pipeline은 deterministic fallback으로 유지하고, 고품질 LLM draft가 필요할 때 Codex CLI provider를 사용합니다.

결정 이유:

- API key 입력 UI를 만들지 않고 사용자의 로컬 Codex CLI 로그인 세션을 활용합니다.
- source summary, concept update, answer, maintenance review를 같은 provider contract로 확장할 수 있습니다.
- Codex 호출 실패, timeout, schema mismatch가 있어도 pipeline은 rule-based fallback으로 계속 동작해야 합니다.

Codex provider를 사용하더라도 raw 파일 수정 금지와 public/private data 정책은 그대로 적용됩니다.

## MCP server를 표준 tool interface로 사용

MCP server는 agent와 wiki 사이의 표준 interface입니다.

결정 이유:

- agent가 파일 구조를 직접 추측하지 않고 `list_wiki_pages`, `read_wiki_page`, `search_wiki`, `answer_question`, `scan_raw_sources` 같은 명시적 tool을 사용할 수 있습니다.
- desktop GUI, CLI, MCP server가 같은 core adapter를 공유하므로 동작 차이를 줄일 수 있습니다.
- wiki maintenance와 answer 저장 흐름을 tool 결과로 검증할 수 있습니다.

MCP tool은 core 로직을 복제하지 않고 `WikiToolAdapter`를 통해 얇게 연결합니다.

## graphify는 탐색과 문맥 확인용

graphify는 위키를 멋지게 보이게 하는 장식 기능이 아니라, source와 concept 사이의 연결을 확인하는 navigation layer입니다.

결정 이유:

- concept page가 어떤 source evidence에서 파생되었는지 빠르게 추적할 수 있습니다.
- answer 주변 문서와 related concept를 긴 목록 대신 graph로 탐색할 수 있습니다.
- broken link나 중복 concept 같은 구조 문제를 눈으로 찾기 쉬워집니다.

현재 graph는 Markdown link와 source evidence 관계를 기반으로 `wiki/graph/graph.json`에 저장됩니다.

## public example과 private runtime state 분리

`examples/finance`는 public-safe fixture와 그 산출물을 보여주는 예제입니다. 루트 `raw/`, `wiki/`, `manifests/` 또는 private raw 자료는 local runtime state로 취급합니다.

결정 이유:

- 공개 저장소에 private note, PDF 원본, 이미지 원본, API key가 섞이는 위험을 줄입니다.
- 예제 도메인은 테스트와 문서 설명에 쓰되, 실제 개인 지식 베이스와 분리합니다.
