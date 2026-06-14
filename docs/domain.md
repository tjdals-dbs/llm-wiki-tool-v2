# Domain Configuration

LLM Wiki Tool v2는 특정 과목이나 산업에 고정된 위키가 아니라, `domain.yml`을 바꿔 여러 지식 도메인에 적용하는 wiki harness입니다. `examples/finance`는 public-safe 샘플 도메인이고, 실제 사용 도메인은 보통 `user_domains/<slug>/` 아래에 둡니다.

## 기본 구조

```text
<domain-root>/
  domain.yml
  raw/
  manifests/
    raw_sources.csv
  wiki/
    sources/
    concepts/
    answers/
    graph/
```

`raw/`는 immutable source layer이고, `wiki/`는 compiled knowledge layer입니다. scanner, summarizer, organizer, GUI, MCP tool, agent provider는 raw 파일을 수정하거나 이동하거나 삭제하지 않습니다.

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

필드 설명:

- `name`: GUI와 문서에서 표시할 도메인 이름입니다.
- `slug`: 파일명과 도메인 식별에 쓰는 짧은 식별자입니다.
- `description`: 도메인의 목적과 범위를 설명합니다.
- `raw_dir`: 사용자가 원본 자료를 넣는 불변 source layer입니다.
- `wiki_dir`: source page, concept page, answer page, graph, index, overview, log가 생성되는 위치입니다.
- `manifest`: raw scan 결과와 처리 상태를 기록하는 CSV 경로입니다.
- `language`: 사용자-facing UI, 진단 메시지, agent answer, 생성 wiki page의 기본 언어 정책입니다.

상대 경로는 `domain.yml`이 위치한 도메인 루트를 기준으로 해석합니다.

## language: ko 정책

`language: ko`는 단순 metadata가 아니라 사용자-facing 출력의 기본 정책입니다.

- GUI label과 상태 메시지
- raw scan, summarize, organize, lint 진단 메시지
- 한국어 raw source 기반 source summary page
- concept page의 reader-facing 설명
- wiki evidence 기반 answer
- maintenance report와 log note

MCP tool name, CLI command, slug, code identifier, 원문 고유명사는 영어 또는 원문 표기를 그대로 사용할 수 있습니다.

## 기본 시연 도메인

이 프로젝트의 MVP와 public-safe sample은 금융투자론/금융시장 개념 위키를 기본 시연 도메인으로 사용합니다. `examples/finance`는 CAPM 같은 금융시장 개념을 예시로 보여주기 위한 샘플이며, GUI 캡처나 기본 데모에서도 같은 성격의 자료를 기준으로 동작을 설명합니다.

다만 도구 자체는 금융 도메인에 고정되어 있지 않습니다. 사용자는 `domain.yml`과 `raw/` 자료를 교체하거나 `user_domains/<slug>/` 아래에 새 도메인을 만들어 보안, 소프트웨어 아키텍처, 연구 노트, 강의 정리 등 다른 지식 도메인의 위키를 만들 수 있습니다.

## public sample과 user domain

`examples/`는 public sample과 테스트 fixture용입니다. 여기에 들어가는 raw는 직접 작성한 public-safe 텍스트여야 합니다.

실제 사용자 자료는 `user_domains/<slug>/` 아래에 둡니다.

```powershell
python scripts\init_user_domain.py --slug finance-private --name "내 금융 위키"
```

`user_domains/<slug>/` 하위의 `domain.yml`, `raw/`, `wiki/`, `manifests/`는 개인 runtime data로 취급하며 Git ignore 대상입니다. 개인 강의자료, 유료 PDF, 저작권 원본, 이미지, HTML 원본, API key는 public repo에 올리지 않습니다.

## 생성 산출물

pipeline과 maintenance workflow는 다음 파일을 생성하거나 갱신할 수 있습니다.

- `manifests/raw_sources.csv`: raw file path, hash, status, source page path
- `wiki/sources/*.md`: raw source별 source summary page
- `wiki/concepts/*.md`: evidence 기반 concept page
- `wiki/answers/*.md`: 저장 가능한 agent answer page
- `wiki/graph/graph.json`: Markdown link와 evidence 관계 graph
- `wiki/index.md`, `wiki/overview.md`, `wiki/log.md`: navigation과 maintenance 기록

answer-derived concept update가 적용되면 기존 concept page의 `## Answer-Derived Notes` 아래에 append됩니다. source evidence가 없거나 이미 적용된 answer-derived draft는 skip되고, log와 maintenance report에 이유가 남습니다.
