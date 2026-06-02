# LLM Wiki MCP Tool v2 PRD

## 1. 제품 목표(Product Goal)

LLM Wiki MCP Tool v2는 재사용 가능한 Markdown 기반 LLM Wiki 유지보수 도구다.

사용자는 자신이 선택한 지식 도메인에 맞는 자료를 `raw/` 폴더에 직접 넣는다. 에이전트는 `raw/` 폴더의 변경점을 감지하고, 새 자료를 소스 요약 페이지(Source Summary Page)로 정리한 뒤, 그 요약 페이지를 근거로 개념 위키 페이지(Concept Page)를 재구성한다. 이후 문서 간 관계 그래프를 만들고, MCP 도구와 데스크톱 GUI를 통해 위키를 검색, 조회, 질의응답, 유지보수할 수 있게 한다.

이 제품은 특정 도메인 전용 위키가 아니다. 사용자가 정의한 어떤 지식 도메인에도 적용할 수 있는 재사용 가능한 LLM Wiki 하네스(harness)를 만드는 것이 목표다.

## 2. 핵심 원칙(Core Principles)

- `raw/`는 불변 원본 계층(immutable source layer)이다.
- 앱, 에이전트, MCP 도구, 스크립트는 `raw/` 파일을 수정, 이동, 삭제, 재작성하면 안 된다.
- 원본 자료(raw material)는 곧바로 개념 페이지(Concept Page)가 되면 안 된다.
- PDF, HTML, 이미지, 스크린샷, Markdown 자료는 먼저 소스 요약 페이지(Source Summary Page)가 되어야 한다.
- 개념 페이지는 반드시 소스 요약 페이지의 근거(source evidence)를 기반으로 만들어야 한다.
- 품질이 낮은 소스 요약은 자동으로 개념 페이지로 승격(promote)하지 않는다.
- 시스템은 불확실성을 인정해야 한다. PDF, 이미지, 웹 기사 등을 충분히 이해하지 못한 경우 `needs_review` 상태로 남겨야 한다.
- 이 위키는 단순 Q&A 화면이 아니다. 에이전트가 위키를 읽고, 답하고, 검토하고, durable wiki page를 업데이트하는 유지보수 루프(maintenance loop)를 가진다.
- 기본 UI, 진단 메시지, 에이전트 답변, 한국어 원본 기반 위키 생성물은 한국어를 기본으로 한다.
- 공개 저장소(public repository)에는 저작권이 있는 강의 PDF, private raw 자료, private 추출 텍스트, API key, local runtime state를 포함하면 안 된다.

## 3. 대상 사용자(Target Users)

- 강의 노트, PDF, 웹 기사, 스크린샷을 개인 지식 위키로 정리하고 싶은 학습자
- 재사용 가능한 MCP 기반 위키 하네스가 필요한 개발자
- 로컬 지식 베이스를 에이전트가 읽고, 검색하고, 답변하고, 유지보수하게 만들고 싶은 사용자
- 고정된 내장 도메인이 아니라 자신만의 지식 도메인을 정의하고 싶은 사용자

## 4. 도메인 모델(Domain Model)

지식 도메인은 사용자가 정의한다.

각 도메인은 `domain.yml`로 설정한다.

예시:

```yaml
name: Finance Investment Theory
slug: finance
description: Educational wiki for finance investment theory.
disclaimer: Educational use only. Not investment advice.
raw_dir: raw
wiki_dir: wiki
manifest: manifests/raw_sources.csv
language: ko
```

샘플 도메인은 금융투자론일 수 있다. 하지만 제품 자체는 금융투자론 전용이 아니어야 한다. 사용자는 `domain.yml`과 `raw/`의 내용을 교체하여 다른 지식 도메인의 위키를 만들 수 있어야 한다.

## 4.1. 언어 정책(Language Policy)

제품의 사용자-facing 기본 언어는 한국어다.

`domain.yml`의 `language` 필드는 장식용 metadata가 아니다. 생성되는 위키 페이지, 에이전트 답변, 진단 메시지, GUI 문구의 기본 언어를 결정하는 실제 정책 값이다.

기본 설정은 다음과 같다.

```yaml
language: ko
```

이 설정에서는 다음 출력이 한국어여야 한다.

- 데스크톱 GUI label
- 버튼 문구
- 상태 메시지
- ingest 진단 메시지
- recommended action 설명
- 한국어 raw source에서 생성된 source summary page
- 한국어 raw source에서 생성된 concept page
- 에이전트 답변
- 사용자에게 보이는 maintenance note
- GUI에 표시되는 lint/review 메시지

영어를 사용할 수 있는 영역은 다음으로 제한한다.

- code identifier
- Python module/package name
- MCP tool name
- CLI command name
- 안정적인 slug가 필요한 file name
- 일반적으로 영어로 쓰는 기술 용어
- 원본 자료 자체가 영어인 경우의 원제목

raw source가 한국어라면 생성되는 source page와 concept page는 한국어여야 한다.

사용자가 한국어로 질문하면 에이전트는 한국어로 답해야 한다.

raw source가 영어이더라도 domain language가 `ko`라면 source summary와 concept explanation은 한국어로 작성하고, 필요한 경우 중요한 원어 용어를 괄호로 병기한다.

이 PRD가 영어 기술 용어를 일부 포함하더라도, 구현 에이전트는 제품 UI나 생성 위키 문서를 영어로 만들어도 된다고 해석하면 안 된다.

## 5. 파일시스템 기반 Raw Ingest

v2의 primary ingest path는 GUI 업로드가 아니라 파일시스템 기반이다.

사용자는 자료를 직접 `raw/` 폴더에 넣는다.

예시:

```text
raw/
  lecture-01.pdf
  market-article.html
  capm-diagram.png
  handwritten-notes.md
```

앱은 기본적으로 파일 업로드 도구처럼 동작하면 안 된다. GUI에는 `raw scan` 또는 `run ingest` 같은 실행 버튼이 있을 수 있지만, 원본 자료의 표준 위치는 항상 `raw/`다.

## 6. 원본 자료 매니페스트(Raw Source Manifest)

시스템은 raw source file을 manifest로 추적한다.

경로:

```text
manifests/raw_sources.csv
```

필수 필드:

```text
path,sha256,source_type,status,detected_at,source_page,notes
```

허용 상태:

```text
new
summarized
needs_review
organized
failed
ignored
```

동작 규칙:

- raw file은 path와 SHA256 hash로 식별한다.
- 새 raw file이 발견되면 manifest에 `new`로 기록한다.
- 기존 raw file의 hash가 바뀌면 재처리가 필요한 것으로 간주한다.
- raw file 자체는 절대 수정하지 않는다.

## 7. 소스 요약 페이지(Source Summary Pages)

모든 raw file은 먼저 소스 요약 페이지(Source Summary Page)로 해석된다.

소스 요약 페이지는 다음 위치에 저장한다.

```text
wiki/sources/
```

source page는 하나의 raw source를 해석한 요약 문서다. 아직 durable concept page가 아니다.

필수 구조:

```md
# Source Title

## Source Metadata

- Raw path:
- SHA256:
- Source type:
- Ingest status:

## Summary

## Key Points

## Evidence

## Visual Evidence

## Candidate Concepts

## Quality Review
```

규칙:

- source page는 raw path와 hash를 provenance로 기록할 수 있다.
- source page는 검토가 필요한 경우가 아니라면 raw extracted text 전체를 덤프하지 않는다.
- source page는 사람이 읽을 수 있는 요약 문서여야 한다.
- source page는 출처(provenance)를 보존해야 한다.
- source가 약하거나 불완전하다면 그 사실을 명확히 표시해야 한다.

## 8. 개념 페이지(Concept Pages)

개념 페이지는 다음 위치에 저장한다.

```text
wiki/concepts/
```

concept page는 하나 이상의 source summary page를 기반으로 합성된 durable wiki page다.

필수 구조:

```md
# Concept Name

## Definition

## Explanation

## Related Concepts

## Source Evidence

## Maintenance Notes
```

규칙:

- concept page는 반드시 근거 기반(evidence-grounded)이어야 한다.
- concept page는 관련 source summary page로 링크해야 한다.
- concept page에는 raw extraction dump가 노출되면 안 된다.
- concept page의 본문 설명에는 `source_path`, `sha256`, `ingest_status`, tool trace 같은 운영 metadata가 노출되면 안 된다.
- candidate concept에 근거가 부족하면 concept page로 승격하지 않는다.
- candidate concept이 기존 concept와 겹치면 새 페이지를 중복 생성하지 말고 기존 concept를 업데이트하거나 병합한다.

## 9. 위키 페이지 유형(Wiki Page Types)

위키 계층은 다음 파일들로 구성된다.

```text
wiki/sources/*.md
wiki/concepts/*.md
wiki/answers/*.md
wiki/index.md
wiki/overview.md
wiki/graph/graph.json
wiki/log.md
```

페이지 유형:

- `source`: 하나의 raw source를 요약한 문서
- `concept`: source evidence 기반으로 합성된 durable knowledge page
- `answer`: 명확한 concept target이 없을 때 유용한 agent answer를 저장하는 fallback page
- `index`: 위키 navigation page
- `overview`: 위키 전체 개요 page

## 10. PDF, HTML, 이미지 처리

Markdown이 아닌 source type은 다음 흐름을 따른다.

```text
raw file
-> source extraction
-> source summary page
-> quality diagnosis
-> candidate concept extraction
-> concept merge or promotion
-> graph rebuild
```

### 10.1. PDF 처리

PDF 처리는 가능하면 page boundary를 보존해야 한다.

PDF extraction은 다음 정보를 수집해야 한다.

- extracted text
- page-level text chunks
- table-like text
- figure/image signal
- optional visual summary

PDF 품질 진단은 다음 요소를 고려해야 한다.

- extracted text length
- substantive sentence count
- key point count
- candidate concept count
- concept evidence count
- metadata/boilerplate leakage
- image-heavy 또는 slide-like 문서 여부

텍스트 추출이 약하면 source를 `needs_review`로 표시하고 다음 recommended action을 포함한다.

```text
recommended_actions:
  - enable_pdf_vision
```

weak PDF는 자동으로 concept page로 승격하면 안 된다.

### 10.2. HTML 처리

HTML 처리는 다음을 제거해야 한다.

- script/style content
- navigation
- footer boilerplate
- edit/history/sidebar UI text
- repeated site chrome

HTML 처리는 다음을 보존해야 한다.

- article title
- headings
- paragraphs
- lists
- tables
- meaningful image alt text

구현은 특정 웹사이트 패턴 하나에만 hardcoding되면 안 된다.

### 10.3. 이미지와 스크린샷 처리

이미지와 스크린샷은 vision-capable path로 처리할 수 있다.

vision adapter가 없으면 시스템은 이미지를 완전히 이해했다고 주장하면 안 된다. 이미지 분석이 불가능한 경우 `needs_review` source page를 만들고 명확한 recommended action을 표시해야 한다.

## 11. 품질 게이트(Quality Gate)

품질 게이트는 약한 source draft가 concept page를 오염시키는 것을 막는다.

각 source summary는 다음 진단 정보를 만들어야 한다.

```text
quality: usable | weak
warnings: [...]
recommended_actions: [...]
concept_count:
concept_evidence_count:
substantive_content_count:
visual_summary_count:
```

경고 예시:

- 요약이 너무 짧음
- 핵심 내용이 없음
- concept 후보가 없음
- concept evidence가 부족함
- 운영 metadata가 본문에 누출됨
- extracted text가 너무 짧음
- 실질 본문이 없음
- PDF vision analysis가 필요함

`quality = weak`이면 자동 concept promotion을 멈춰야 한다.

## 12. 에이전트 역할(Agent Roles)

에이전트 시스템은 역할별로 나뉜다. 실제 구현에서는 하나의 persistent worker 안에서 실행될 수 있지만, 각 역할의 책임은 분리되어야 한다.

### 12.1. Raw Scanner Agent

- `raw/`를 스캔한다.
- SHA256 hash를 계산한다.
- `manifests/raw_sources.csv`와 비교한다.
- 새 파일 또는 변경된 파일을 표시한다.

### 12.2. Source Summarizer Agent

- raw material을 source summary page로 변환한다.
- Markdown, PDF, HTML, image-like source를 처리한다.
- provenance를 보존한다.
- 가능한 한 raw text dump를 피한다.

### 12.3. Quality Review Agent

- source summary quality를 평가한다.
- weak source를 `needs_review`로 표시한다.
- `enable_pdf_vision`, `manual_review` 같은 action을 추천한다.

### 12.4. Concept Organizer Agent

- source page에서 candidate concept를 추출한다.
- 근거가 있는 concept를 승격한다.
- 기존 concept와 겹치는 경우 병합한다.
- 근거가 부족한 후보는 drop하거나 pending 상태로 남긴다.

### 12.5. Retriever Agent

- wiki page를 검색한다.
- source page와 concept page를 읽는다.
- graph neighbor를 사용해 관련 context를 모은다.

### 12.6. Answer Agent

- wiki evidence를 기반으로 사용자 질문에 답한다.
- 기본적으로 한국어로 답한다.
- 근거가 부족하면 부족하다고 말한다.
- 지원되지 않는 주장을 사실처럼 말하지 않는다.

### 12.7. Maintenance Agent

- 유용한 답변을 기존 concept page 또는 answer page로 라우팅한다.
- raw file을 재작성하지 않는다.
- 사람이 작성한 synthesis를 조용히 대체하지 않는다.

### 12.8. Review Agent

- lint check를 실행한다.
- graph/page count를 확인한다.
- maintenance status를 보고한다.

## 13. MCP 도구(MCP Tools)

MCP server는 외부 agent와 wiki 사이의 표준 인터페이스다.

필수 도구:

```text
list_wiki_pages(page_type=None)
read_wiki_page(path)
search_wiki(query, limit=10)
get_wiki_graph()
get_related_pages(path, depth=1)
ask_wiki_context(query, limit=5)
scan_raw_sources()
summarize_new_sources(limit=None)
organize_pending_sources(limit=None)
apply_wiki_update(question, answer, used_pages, related_pages, status="ok")
run_wiki_lint()
```

도구 동작 규칙:

- 모든 tool은 선택된 domain 안에서 동작해야 한다.
- path traversal을 차단해야 한다.
- 명시적으로 설정하지 않는 한 ignored private folder를 읽으면 안 된다.
- tool은 `raw/`를 변경하면 안 된다.
- update tool은 wiki/manifest/log 계층에만 쓸 수 있다.

## 14. 데스크톱 GUI 요구사항(Desktop GUI Requirements)

GUI는 파일 업로드 도구가 아니라 wiki viewer와 agent control panel이다.

필수 layout:

```text
Left panel: wiki page list and search
Center panel: selected wiki page and local graph
Right panel: wiki agent, raw scan status, maintenance status
```

필수 GUI action:

- raw folder scan
- summarize new sources
- organize pending sources
- run wiki lint
- ask wiki agent
- select wiki pages
- graph node click navigation

필수 GUI display:

- source/concept/answer page grouping
- source quality status
- warning과 recommended action
- pending source count
- concept promotion/merge/drop result
- selected page 주변 graph neighborhood
- used pages와 related pages를 분리해서 보여주는 agent answer panel

agent answer body는 GUI가 별도로 렌더링하는 `used pages`, `related pages` 같은 metadata section을 중복 출력하면 안 된다.

## 15. Graphify

위키 graph는 Markdown link와 source-concept 관계를 기반으로 생성한다.

node type:

```text
source
concept
answer
index
overview
```

edge type:

```text
mentions
derived_from
related_to
updated_by_agent
```

graph 요구사항:

- graph는 `wiki/graph/graph.json`에 저장한다.
- GUI는 selected page 주변의 local neighborhood를 보여줘야 한다.
- node label은 짧게 표시한다.
- full page title은 tooltip으로 표시할 수 있다.
- graph node를 클릭하면 해당 wiki page로 이동해야 한다.

## 16. 데이터와 개인정보 정책(Data and Privacy Policy)

public repository에 포함할 수 있는 것:

- source code
- project docs
- sample domain config
- 직접 작성한 sample Markdown note
- public-safe sample note에서 생성한 sample wiki page

public repository에 포함하면 안 되는 것:

- 저작권이 있는 강의 PDF
- private raw file
- private screenshot
- private HTML capture
- extracted private text
- API key
- local runtime state
- 의도적으로 sample data로 포함하지 않은 user-specific answer log

권장 ignore path:

```text
raw/private/
raw/**/*.pdf
raw/**/*.zip
raw/**/*.png
raw/**/*.jpg
raw/**/*.jpeg
raw/**/*.html
.runtime/
```

단, `examples/` 아래에 의도적으로 둔 public-safe sample file은 예외로 허용할 수 있다.

## 17. 인수 기준(Acceptance Criteria)

- 사용자는 `domain.yml`로 domain을 정의할 수 있다.
- 사용자는 `raw/`에 파일을 넣을 수 있다.
- Raw Scanner가 새 raw file을 감지한다.
- raw file은 앱, 에이전트, MCP tool, script에 의해 수정되지 않는다.
- SHA256 hash가 `manifests/raw_sources.csv`에 기록된다.
- 새 raw file은 source page로 요약될 수 있다.
- source page는 metadata, summary, key points, evidence, candidate concepts, quality review를 포함한다.
- weak PDF summary는 `needs_review`로 표시된다.
- weak PDF는 자동으로 concept page로 승격되지 않는다.
- concept page는 evidence-backed source summary에서만 생성된다.
- 기존 concept와 겹치는 내용은 duplicate page를 만들지 않고 update 또는 merge한다.
- wiki graph가 생성되고 GUI에서 볼 수 있다.
- MCP tool로 page list/read/search/graph 조회가 가능하다.
- MCP tool로 raw scan과 pending source organization이 가능하다.
- GUI는 page list, selected content, graph, agent answer, source quality, maintenance status를 표시한다.
- 에이전트는 wiki evidence를 기반으로 답한다.
- wiki evidence가 부족하면 에이전트는 근거가 부족하다고 말한다.
- 완료 전에 lint와 test가 통과해야 한다.

## 18. 테스트 계획(Test Plan)

필수 테스트:

```text
domain config loading
raw scan detects new files
raw scan records sha256
raw scan does not modify raw files
manifest status transitions
Markdown source summarization
PDF source summarization
HTML source summarization
image source review fallback
PDF page boundary preservation
weak PDF quality diagnosis
weak PDF auto-promotion prevention
metadata leakage prevention
candidate concept extraction
unsupported generic concept filtering
source-to-concept promotion
existing concept merge
concept evidence requirement
graph generation
graph related page traversal
MCP tool registry
MCP path traversal blocking
GUI shell rendering
GUI source quality status rendering
agent no-evidence answer
agent answer metadata separation
wiki lint
```

완료 전 검증:

```powershell
python -m unittest discover -v
python -m compileall wiki_tool scripts tests
python scripts/lint_wiki.py --domain examples/finance/domain.yml
```

## 19. 비목표(Non-Goals)

- GUI drag-and-drop upload를 primary ingest path로 만들지 않는다.
- raw file을 수정하지 않는다.
- diagnostics가 weak라고 판단한 extracted PDF text를 신뢰 가능한 자료처럼 취급하지 않는다.
- source evidence 없는 concept page를 만들지 않는다.
- 특정 웹사이트, 특정 수업, 특정 도메인에 hardcoding하지 않는다.
- finance sample domain에서 투자 조언을 제공하지 않는다.
- 기본 wiki viewer와 MCP server 실행에 hosted LLM API key를 요구하지 않는다.
- 명시적으로 요청받지 않는 한 v2에서 browser-based GUI를 구현하지 않는다. primary GUI는 desktop app이다.

## 20. 초기 구현 순서(Initial Implementation Order)

1. project docs 생성
   - `docs/domain.md`
   - `docs/decision-rounds.md`
   - `docs/prd.md`
2. domain config와 wiki schema 정의
3. raw scanner와 manifest 구현
4. Markdown source summary generation 구현
5. source page와 concept page builder 구현
6. PDF/HTML source handling 구현
7. quality gate 구현
8. concept organization 구현
9. graph generation 구현
10. MCP server tools 구현
11. desktop GUI 구현
12. persistent agent runtime 구현
13. tests와 verification script 추가

## 21. 구현 프롬프트(Implementation Prompt)

이 PRD를 source of truth로 사용하라.

구현은 test-first 방식으로 점진적으로 진행한다. GUI upload flow부터 시작하지 마라. 먼저 immutable `raw/` source layer, manifest tracking, source summary generation, quality-gated concept organization을 안정화하라.

목표는 어떤 입력 파일이든 무리하게 wiki page로 밀어 넣는 도구가 아니라, 신뢰 가능한 LLM Wiki maintenance harness를 만드는 것이다.
