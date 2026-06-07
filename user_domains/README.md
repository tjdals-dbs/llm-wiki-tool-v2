# User Domains

이 폴더는 실제 사용자 도메인의 기본 위치입니다.

`user_domains/<slug>/` 아래의 개인 도메인 폴더는 Git에서 ignore됩니다. 개인 `domain.yml`, `raw/`, `manifests/`, `wiki/` 산출물은 public repo에 올리지 마세요.

다음 단계에서 `scripts/init_user_domain.py`가 아래 구조를 자동 생성할 예정입니다. 지금은 필요한 경우 수동으로 같은 구조를 만들 수 있습니다.

```text
user_domains/
  <user-domain>/
    domain.yml
    raw/
    manifests/
    wiki/
      sources/
      concepts/
      answers/
      graph/
```

개인 raw 자료, PDF, HTML, 이미지, 생성된 wiki 산출물은 로컬 runtime data입니다. 공개 저장소에 커밋하지 마세요.
