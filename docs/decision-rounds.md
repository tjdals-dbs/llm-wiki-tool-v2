# Decision Rounds

이 문서는 v2 구현에서 반복적으로 등장한 설계 결정을 짧게 고정해 둔 기록입니다. 상세 요구사항의 source of truth는 루트 `prd.md`이고, 이 문서는 현재 구현 방향을 이해하기 위한 보조 문서입니다.

## raw folder 기반 ingest

v2의 primary ingest path는 GUI upload/dropzone이 아니라 `raw/` 폴더입니다.

결정 이유:

- 사용자가 원본 파일의 위치와 변경 이력을 직접 통제할 수 있습니다.
- CLI, GUI, MCP tool, agent runtime이 같은 filesystem contract를 공유합니다.
- public/private raw 경계를 명확히 유지할 수 있습니다.

따라서 desktop GUI는 파일 업로드 앱처럼 동작하지 않습니다. GUI는 raw scan, summarize, organize, lint, maintenance workflow를 실행하고 결과를 보여주는 maintenance surface입니다.

## source summary -> concept page 2단계

raw source를 바로 concept page로 만들지 않습니다.

결정 이유:

- raw source는 Markdown, PDF extraction text, HTML body, image-heavy source처럼 품질과 구조가 제각각입니다.
- source summary page가 provenance, evidence, candidate concept, quality review를 먼저 정리해야 concept merge가 안전합니다.
- concept page는 durable knowledge page이므로 source evidence 없이 생성되면 안 됩니다.

현재 pipeline은 `raw -> wiki/sources/*.md -> wiki/concepts/*.md` 순서를 따릅니다.

## weak source는 needs_review로 차단

텍스트가 부족하거나 extraction confidence가 낮은 source는 자동 concept promotion 대상이 아닙니다.

결정 이유:

- 약한 source를 concept page로 승격하면 wiki 전체 품질이 흔들립니다.
- 사용자가 OCR, vision, 수동 요약 같은 보완 작업이 필요한 지점을 명확히 볼 수 있습니다.

`needs_review`는 실패가 아니라 안전장치입니다.

## MCP server를 표준 tool interface로 사용

MCP server는 agent와 wiki 사이의 표준 interface입니다.

결정 이유:

- agent가 파일 구조를 직접 추측하지 않고 명시적 tool을 사용합니다.
- desktop GUI, CLI, MCP server가 같은 `WikiToolAdapter`를 공유하므로 동작 차이를 줄일 수 있습니다.
- answer 저장, answer-derived maintenance, graph/lint 결과를 tool contract로 검증할 수 있습니다.

GUI의 Wiki Agent 패널도 MCP tool registry를 우선 route로 사용하고, direct adapter 호출은 fallback으로만 남깁니다.

## Codex CLI provider 우선, rule_based fallback 유지

고품질 LLM draft가 필요한 경우 Codex CLI provider를 사용하고, deterministic fallback은 계속 유지합니다.

결정 이유:

- OpenAI API key 입력 UI를 만들지 않고 사용자의 로컬 Codex CLI 로그인 세션을 활용합니다.
- answer, ingest, concept, review role을 같은 provider contract로 확장할 수 있습니다.
- CLI 호출 실패, timeout, schema mismatch가 있어도 pipeline은 rule-based fallback으로 계속 동작해야 합니다.

Gemini CLI는 detection/wrapper skeleton만 준비되어 있습니다. 실제 role 연결은 아직 하지 않았습니다. Claude provider는 현재 제외되어 있습니다.

## graphify는 탐색과 문맥 확인용

graphify는 위키를 화려하게 보이게 하는 장식 기능이 아니라 source, concept, answer의 연결을 확인하는 navigation layer입니다.

결정 이유:

- concept page가 어떤 source evidence에서 나왔는지 빠르게 추적할 수 있습니다.
- answer 주변 문서와 related concept를 긴 목록 대신 graph로 탐색할 수 있습니다.
- broken link나 고립된 문서 같은 구조 문제를 눈으로 찾기 쉬워집니다.

현재 graph는 Markdown link와 evidence 관계를 기반으로 `wiki/graph/graph.json`에 저장됩니다.

## answer 저장은 policy 기반 자동 저장

agent answer를 모두 저장하지 않고, deterministic save decision이 저장 여부를 결정합니다.

결정 이유:

- fallback, no_evidence, 빈 답변은 wiki 지식으로 저장하면 안 됩니다.
- evidence-backed answer만 재사용 가능한 answer page가 됩니다.
- 사용자가 저장 버튼을 누르는 UI보다 maintenance loop 안에서 일관된 정책으로 처리하는 편이 자동화 흐름에 맞습니다.

같은 질문 또는 suggested title은 같은 answer page를 업데이트하여 중복 파일이 계속 늘어나지 않게 합니다.

## answer-derived concept update는 append-only

저장된 answer page는 maintenance workflow에서 concept update 후보가 될 수 있지만, source evidence가 있어야 실제 반영됩니다.

결정 이유:

- answer가 concept page만 근거로 삼으면 지식이 순환할 수 있습니다.
- source-backed answer-derived note는 기존 concept를 보강할 수 있지만, 사람이 작성한 본문을 덮어쓰면 안 됩니다.
- marker 기반 idempotency가 있어야 maintenance를 여러 번 실행해도 같은 note가 중복되지 않습니다.

현재 적용 위치는 기존 concept page의 `## Answer-Derived Notes` section입니다. 새 concept 자동 생성이나 answer->concept 본문 병합은 아직 하지 않습니다.

## public sample과 private runtime state 분리

`examples/finance`는 public-safe sample과 테스트 fixture입니다. 실제 개인 도메인은 `user_domains/<slug>/` 아래에 둡니다.

결정 이유:

- 공개 저장소에 private note, 강의 PDF, 유료 자료, 이미지 원본, API key가 섞일 위험을 줄입니다.
- sample domain은 기능 설명과 테스트에 쓰고, 실제 개인 지식 베이스는 Git ignore되는 runtime data로 분리합니다.
