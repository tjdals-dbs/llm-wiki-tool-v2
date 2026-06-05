# Domain 설정

LLM Wiki Tool v2는 특정 금융투자론 도구가 아니라, 도메인을 교체할 수 있는 wiki harness입니다. 도메인은 `domain.yml` 하나로 정의하며, 같은 pipeline을 다른 `raw/`, `wiki/`, `manifest` 경로에 적용할 수 있습니다.

## domain.yml 예시

```yaml
name: Finance Investment Theory
slug: finance
description: Educational wiki for finance investment theory.
raw_dir: raw
wiki_dir: wiki
manifest: manifests/raw_sources.csv
language: ko
```

`examples/finance/domain.yml`은 public-safe 예제입니다. 제품이 금융투자론에 고정되어 있다는 뜻은 아닙니다.

## 필드

- `name`: GUI와 문서에서 표시할 도메인 이름입니다.
- `slug`: 도메인을 식별하는 안정적인 짧은 이름입니다.
- `description`: 도메인의 목적이나 범위를 설명합니다.
- `raw_dir`: 사용자가 원본 자료를 넣는 불변 source layer입니다.
- `wiki_dir`: source page, concept page, graph, answer page가 생성되는 wiki 계층입니다.
- `manifest`: raw scan 결과와 처리 상태를 기록하는 CSV 경로입니다.
- `language`: UI, 진단 메시지, agent 답변, 생성 wiki page의 기본 언어 정책입니다.

경로 값은 `domain.yml`이 있는 도메인 루트를 기준으로 해석됩니다.

## language: ko 정책

`language: ko`는 단순 metadata가 아닙니다. 한국어 사용자를 기본 대상으로 하므로 다음 출력은 한국어 중심으로 작성되어야 합니다.

- desktop GUI label과 상태 메시지
- raw scan, summarize, organize, lint 진단 메시지
- 한국어 raw source 기반 source summary page
- concept page의 reader-facing 설명
- wiki evidence 기반 agent answer
- maintenance report와 review note

영어가 자연스러운 code identifier, MCP tool name, CLI command, slug, 원문 고유명사는 그대로 사용할 수 있습니다.

## raw 계층 정책

`raw_dir` 아래 파일은 원본입니다. scanner, summarizer, organizer, MCP tool, GUI, Codex provider는 raw 파일을 수정, 이동, 삭제하지 않습니다.

처리 결과는 다음 생성 계층에 기록됩니다.

- `manifest`: raw 파일의 path, sha256, status, source page 경로
- `wiki/sources/`: raw source별 source summary page
- `wiki/concepts/`: evidence 기반 concept page
- `wiki/answers/`: 저장된 answer page
- `wiki/graph/graph.json`: Markdown link와 evidence 관계 graph
- `wiki/log.md`: maintenance run 기록

## sample raw 정책

public repo에 포함되는 sample raw는 public-safe 텍스트 fixture여야 합니다.

- 허용: 직접 작성한 짧은 Markdown 예제
- 금지: private note, 강의 PDF 원본, 저작권 이미지, HTML 원본, API key, `.env`, local runtime state
- `raw/private/`와 `examples/**/raw/private/`는 공개 예제와 scan 경계 밖으로 취급합니다.

실제 개인 지식 자료를 사용할 때는 별도 로컬 도메인을 만들고 해당 raw/wiki/manifest 산출물을 커밋하지 않는 방식이 안전합니다.
