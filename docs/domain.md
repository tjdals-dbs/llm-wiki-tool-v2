# Domain Model

`domain.yml`은 위키가 다루는 지식 도메인과 파일 계층을 정의한다.

필수 값:

- `name`: 도메인 표시 이름
- `slug`: 안정적인 도메인 식별자
- `description`: 도메인 설명
- `raw_dir`: 불변 원본 계층 경로
- `wiki_dir`: 생성된 wiki 계층 경로
- `manifest`: raw source manifest 경로
- `language`: UI, 진단 메시지, agent 답변, 생성 wiki 문서의 기본 언어

`raw_dir` 아래 파일은 수정, 이동, 삭제하지 않는다. 도구는 `manifest`, `wiki`, `graph`, `answers` 같은 생성 계층만 갱신한다.
