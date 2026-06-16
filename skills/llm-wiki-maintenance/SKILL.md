---
name: llm-wiki-maintenance
description: Use when operating this repository's LLM Wiki maintenance harness, including creating user domains, adding raw material, running GUI wiki updates, validating MCP readonly tools, and preserving raw/privacy/evidence boundaries.
---

# LLM Wiki Maintenance

Use this skill when working inside the LLM Wiki Tool v2 repository.

## Workflow

1. Check the active domain. Prefer `--domain`, then `LLM_WIKI_DOMAIN`, then `user_domains/<slug>/domain.yml`, then `examples/finance/domain.yml`.
2. Add user material under `user_domains/<slug>/raw/`. Do not edit raw files during maintenance.
3. Run the desktop app with `run_app.bat` on Windows or `./run_app.sh` on macOS after setup.
4. In the GUI, use `위키 업데이트` to run scan, source summary, concept organization, answer-derived concept updates, graph/navigation refresh, and lint.
5. Use MCP `--toolset readonly` for external agents by default. Use `--toolset full` only when intentionally exposing update tools.
6. Validate changed code or docs with the narrow relevant tests first, then the full verification commands before release.

## Guardrails

- Treat `raw/` as immutable. Never rewrite, move, or delete raw source material.
- Do not commit `.env`, private raw data, or `user_domains/<slug>/` runtime output.
- Do not stage generated `examples/finance/wiki/*` or manifest changes unless the task explicitly asks for sample output updates.
- Require source evidence for answer-derived concept updates.
- Preserve human-authored concept content. Append or section-merge generated notes instead of replacing whole pages.
- Keep MCP readonly/context tools as the default path for external agents.

## Useful Commands

```powershell
setup.bat
run_app.bat
python scripts\run_app.py --check
python scripts\init_user_domain.py --slug my-wiki --name "내 위키"
python scripts\lint_wiki.py --domain examples\finance\domain.yml
python scripts\run_mcp_server.py --domain examples\finance\domain.yml --transport stdio --toolset readonly
```

```bash
./setup.sh
./run_app.sh
python3 scripts/run_app.py --check
python3 scripts/run_mcp_server.py --domain examples/finance/domain.yml --transport stdio --toolset readonly
```
