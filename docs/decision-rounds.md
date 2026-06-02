# Decision Rounds

## 2026-06-03

- Python 표준 라이브러리 중심 코어로 시작한다.
- GUI는 browser-based GUI가 아니라 `tkinter` 데스크톱 앱으로 제공한다.
- GUI primary ingest path는 파일 업로드가 아니라 `raw scan`, `source summary`, `concept organization`, `lint` action이다.
- MCP tool은 코어 로직을 직접 품지 않고 `WikiToolAdapter`와 registry를 통해 얇게 연결한다.
- source summary 품질이 약하면 `needs_review`로 남기고 concept page로 자동 승격하지 않는다.
- public-safe 예제는 `examples/` 아래에만 두고, root `raw/`, `wiki/`, `manifests/`는 local state로 취급한다.
