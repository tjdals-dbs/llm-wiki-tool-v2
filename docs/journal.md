# Implementation Journal

This journal summarizes implementation iterations for MCP-based LLM Wiki Tool v2.
It is not a real-time activity log. Confidence is higher when an item is backed by current source files, tests, or commit history, and lower when the item is inferred from broader project context.

## Iteration: Raw Source Layer And Domain Configuration

- did: Built a domain-based workspace model with `domain.yml`, immutable `raw/` inputs, generated wiki outputs, and raw source manifests.
- why: The tool needed a domain-switchable wiki harness where source materials can be added without letting agents mutate original files.
- result: Domain configs now resolve `raw_dir`, `wiki_dir`, and manifest paths, while scanner tests assert raw files are recorded without modification.
- evidence: `wiki_tool/config.py`, `wiki_tool/scanner.py`, `wiki_tool/manifest.py`, `tests/test_domain_config.py`, `tests/test_raw_scanner.py`, `tests/test_repository_privacy.py`.
- confidence: high.

## Iteration: Source Summary Generation

- did: Implemented raw source summarization into structured source pages with summary, key points, evidence, candidate concepts, and quality review sections.
- why: Raw Markdown, extracted PDF text, and HTML text needed to become readable wiki source summaries instead of copied text blocks.
- result: Source summary generation is tested for Markdown, PDF text, HTML cleanup, weak image/PDF review cases, and Codex ingest fallback behavior.
- evidence: `wiki_tool/summarizer.py`, `wiki_tool/extractors.py`, `wiki_tool/quality.py`, `tests/test_source_summarizer.py`, `tests/test_wiki_navigation_and_source_types.py`.
- confidence: high.

## Iteration: Concept Candidate Filtering

- did: Added domain-independent concept phrase filtering to reject sentence fragments and keep short noun phrases, acronyms, and technical terms.
- why: Candidate concept lists were being polluted by explanatory fragments that could become bad concept pages and graph nodes.
- result: Candidate filtering now rejects overlong or sentence-like phrases before concept promotion and graph generation.
- evidence: `wiki_tool/concept_filter.py`, `tests/test_concept_filter.py`, `tests/test_concept_graph_lint.py`.
- confidence: high.

## Iteration: Source To Concept Promotion And Merge

- did: Built concept organization that promotes source summaries into concept pages, merges existing concepts, preserves human-authored content, and maintains source evidence links.
- why: Source summaries should lead to reusable concept pages without duplicating aliases or overwriting manual edits.
- result: Tests cover concept promotion, alias matching, merge preservation, weak source skipping, link normalization, and graph/lint consistency.
- evidence: `wiki_tool/organizer.py`, `wiki_tool/graph.py`, `wiki_tool/lint.py`, `tests/test_concept_graph_lint.py`.
- confidence: high.

## Iteration: Wiki Navigation And Graph Maintenance

- did: Added index, overview, log, and graph generation paths for wiki outputs.
- why: Users and agents need navigable wiki structure, maintenance history, and graph context after generated pages change.
- result: Navigation pages and graph JSON are generated and refreshed after source/concept/answer changes in tested workflows.
- evidence: `wiki_tool/navigation.py`, `wiki_tool/graph.py`, `tests/test_wiki_navigation_and_source_types.py`, `tests/test_mcp_tools.py`, commit `b7666ec`.
- confidence: high.

## Iteration: MCP Tool Adapter And Registry

- did: Created a `WikiToolAdapter` and MCP tool registry for list/read/search/context/graph/pipeline/answer/update functions.
- why: The project needed a stable MCP-facing interface between agents and the local wiki.
- result: Registry tests verify required tool names and adapter behavior, including path traversal protection and answer maintenance tools.
- evidence: `wiki_tool/mcp_tools.py`, `wiki_tool/mcp_registry.py`, `wiki_tool/mcp_server.py`, `tests/test_cli_and_registry.py`, `tests/test_mcp_tools.py`, `tests/test_answer_and_mcp_server.py`.
- confidence: high.

## Iteration: Codex Provider Hooks

- did: Connected Codex CLI provider paths for answer, ingest, concept, and review hooks, with rule-based fallback on failure.
- why: Rule-based wiki operations needed an optional higher-quality LLM path without requiring OpenAI API key entry.
- result: Codex bridge and hook tests cover JSON parsing, mixed CLI logs, timeout/non-zero failures, sandbox flags, prompt contracts, and fallback behavior.
- evidence: `wiki_tool/codex_agent.py`, `wiki_tool/agent_hooks.py`, `wiki_tool/agent_provider.py`, `tests/test_codex_agent.py`, `tests/test_agent_hooks.py`, `tests/test_answer_and_mcp_server.py`.
- confidence: high.

## Iteration: Codex Provider Smoke Runner

- did: Added a smoke runner for local Codex provider verification, including answer smoke and optional temporary-domain pipeline smoke.
- why: Mock tests alone could not prove the local Codex CLI path worked in the user's environment.
- result: The smoke runner checks environment summary, CLI availability, answer provider status, fallback status, evidence counts, and temporary raw-to-concept pipeline behavior without modifying sample domains.
- evidence: `scripts/smoke_codex_provider.py`, `tests/test_smoke_codex_provider.py`.
- confidence: high.

## Iteration: Environment File Loading

- did: Added `.env` loading support and `.env.example` for provider configuration without external dotenv dependencies.
- why: Local Codex provider settings needed a repeatable configuration path while preserving explicit environment variable precedence.
- result: Tests cover missing `.env`, comments, blank lines, quoted values, non-overriding behavior, and smoke runner env summary behavior.
- evidence: `wiki_tool/env_loader.py`, `.env.example`, `tests/test_env_loader.py`, `scripts/smoke_codex_provider.py`.
- confidence: high.

## Iteration: Unit Test Environment Isolation

- did: Isolated subprocess-based unit tests from local `.env` provider settings by forcing `rule_based` in test subprocess environments.
- why: Local `LLM_WIKI_AGENT_PROVIDER=codex` settings could make normal unit tests call real Codex CLI and run slowly.
- result: Runtime and CLI subprocess tests now pass explicit test env values so `unittest discover` remains fast and deterministic.
- evidence: `tests/test_agent_runtime.py`, `tests/test_cli_and_registry.py`.
- confidence: high.

## Iteration: Public Sample Domain Hygiene

- did: Regenerated and cleaned finance example wiki outputs in earlier work, and kept later generated `examples/finance` noise out of unrelated commits.
- why: Public sample data should remain safe and useful, but generated outputs should not pollute feature commits unless explicitly requested.
- result: Privacy tests and repeated staged-file checks keep private raw data and generated noise outside feature commits.
- evidence: `examples/finance/domain.yml`, `examples/finance/raw/capm.md`, `tests/test_repository_privacy.py`, recurring `git status` checks in recent implementation turns.
- confidence: medium.

## Iteration: Project Documentation Structure

- did: Reworked public-facing documentation for project concepts, domain configuration, decisions, PRD summary, and agent boundaries.
- why: The implementation had grown beyond the original docs, so users needed a repo-style explanation of what the tool is and how it is operated.
- result: Documentation now explains raw immutability, source summaries, concept pages, graphify, MCP tools, Codex provider, desktop GUI, domain policies, and agent permissions.
- evidence: `README.md`, `docs/domain.md`, `docs/decision-rounds.md`, `docs/prd.md`, `docs/agent-spec.md`, commit `5750881`.
- confidence: high.

## Iteration: PySide6 Desktop GUI Replacement

- did: Replaced the earlier tkinter GUI with a PySide6 desktop GUI using a three-panel layout.
- why: The GUI needed a more usable desktop experience while keeping v2's raw-folder maintenance model and MCP-first agent path.
- result: GUI files now include split modules for runtime, presenter, domain controls, navigation, graph, chat, and styles.
- evidence: `wiki_tool/desktop_gui.py`, `wiki_tool/desktop_runtime.py`, `wiki_tool/desktop_presenter.py`, `wiki_tool/desktop_navigation.py`, `wiki_tool/desktop_graph.py`, `wiki_tool/desktop_chat.py`, `wiki_tool/desktop_styles.py`, `tests/test_desktop_gui.py`, `tests/test_desktop_gui_modules.py`, commits `8c78d34`, `8b33444`.
- confidence: high.

## Iteration: GUI Background Workers

- did: Moved long-running agent and maintenance operations into background task workers.
- why: Codex/MCP calls and concept organization could block the PySide event loop and make the GUI appear frozen.
- result: Agent question handling and maintenance actions now use background task results, pending messages, refresh flags, and failure messages.
- evidence: `wiki_tool/desktop_runtime.py`, `wiki_tool/desktop_gui.py`, `tests/test_desktop_gui.py`, commits `8354f2a`, `ac410de`.
- confidence: high.

## Iteration: GUI Chat Panel

- did: Changed the right-side agent output from a single overwritten response area into a chat-style log with pending assistant messages.
- why: Users needed previous questions and answers to remain visible during a GUI session, while maintenance messages should not erase chat content.
- result: Chat helper tests cover user/assistant message structure, pending replacement, supporting text for used/related pages, and separation from maintenance status text.
- evidence: `wiki_tool/desktop_chat.py`, `wiki_tool/desktop_gui.py`, `tests/test_desktop_gui.py`, commit `ac3ef0e`.
- confidence: high.

## Iteration: GUI Navigation And Status UX

- did: Improved left navigation grouping, raw folder access, domain controls, maintenance button structure, provider status display, and stable one-line status text.
- why: The GUI needed to feel like wiki navigation rather than internal file-type lists, and operational status needed to be visible without destabilizing layout.
- result: Tests cover navigation grouping, enabled non-selectable headers, raw folder opening without modifying files, provider summary/detail display, advanced maintenance toggle, and elided status messages.
- evidence: `wiki_tool/desktop_navigation.py`, `wiki_tool/desktop_domain.py`, `wiki_tool/desktop_styles.py`, `tests/test_desktop_gui.py`, commits `f87c791`, `34b543c`, `3b22cc2`, `e2caa8c`, `7386931`.
- confidence: high.

## Iteration: User Domain Storage And Initialization

- did: Added `user_domains/` repository boundary, CLI domain initialization, GUI domain selection, and GUI user-domain creation.
- why: Real user domains must live outside public sample fixtures and be ignored by Git by default.
- result: Users can create local domain structures with `domain.yml`, `raw/`, `manifests/`, and `wiki/` subfolders, and the GUI can discover/switch domains.
- evidence: `user_domains/.gitkeep`, `user_domains/README.md`, `wiki_tool/user_domain.py`, `scripts/init_user_domain.py`, `tests/test_user_domain_init.py`, `tests/test_repository_privacy.py`, commits `fdf9a5d`, `cad0615`, `2512567`, `c7cc1fb`.
- confidence: high.

## Iteration: Provider Policy Cleanup And Gemini Skeleton

- did: Removed the Claude provider after experimentation and added a Gemini CLI detection/wrapper skeleton without wiring Gemini into answer/review/ingest/concept roles.
- why: Provider work was getting too broad, so the project narrowed to Codex plus rule-based behavior while keeping Gemini as a future extension point.
- result: Current provider tests cover Codex/rule-based config, auto detection, Gemini command detection, Gemini wrapper failure modes, and unsupported-provider fallback.
- evidence: `wiki_tool/agent_provider.py`, `wiki_tool/gemini_agent.py`, `tests/test_agent_provider.py`, `tests/test_gemini_agent.py`, commits `d6b7f06`, `886d7e2`.
- confidence: high.

## Iteration: Answer Save Decision

- did: Added deterministic answer save decision metadata to answer results.
- why: The system should not save every agent answer; only non-fallback, evidence-backed, successful answers should become answer pages.
- result: Tests cover save vs skip decisions for ok answers with evidence/used pages, fallback answers, no-evidence answers, empty answers, and title generation.
- evidence: `wiki_tool/answer_save_decision.py`, `tests/test_answer_save_decision.py`, commit `5794dd8`.
- confidence: high.

## Iteration: Agent Answer Auto-Save

- did: Connected save-eligible agent answers to automatic `wiki/answers/` persistence through the GUI/presenter workflow.
- why: Evidence-backed answers should become reusable wiki material without requiring a manual save button.
- result: GUI presenter tests cover save execution, skip behavior, save failure behavior, status messages, and page refresh flags.
- evidence: `wiki_tool/desktop_presenter.py`, `wiki_tool/mcp_tools.py`, `tests/test_desktop_gui.py`, `tests/test_mcp_tools.py`, commit `ebb54cf`.
- confidence: high.

## Iteration: Answer Page Deduplication

- did: Stabilized answer page storage so repeated saves of the same question/title update an existing page instead of creating duplicates.
- why: Automatic answer saving could otherwise grow repeated answer files for the same question.
- result: Tests verify one answer file after repeated saves, `created` metadata preservation, `updated` metadata changes, and created/updated return flags.
- evidence: `wiki_tool/mcp_tools.py`, `tests/test_mcp_tools.py`, commit `d1bb115`.
- confidence: high.

## Iteration: Answer Save Navigation Refresh

- did: Refreshed index, overview, log, and graph after answer page creation or update.
- why: Saved answers should appear immediately in navigation and graph surfaces.
- result: Tests verify answer pages appear in page lists and graph nodes, and log entries record answer save/update events.
- evidence: `wiki_tool/mcp_tools.py`, `wiki_tool/navigation.py`, `wiki_tool/graph.py`, `tests/test_mcp_tools.py`, commit `62fdb5b`.
- confidence: high.

## Iteration: Answer Maintenance Candidates

- did: Added scanning and analysis of stored answer pages as maintenance candidates.
- why: Saved answers can contain knowledge that may later become concept updates, but should not be merged blindly.
- result: Candidate analysis extracts answer path, title, question, answer preview, used pages, related pages, evidence, status, and metadata while tolerating malformed pages.
- evidence: `wiki_tool/answer_maintenance.py`, `tests/test_answer_maintenance.py`, commit `5ca08b1`.
- confidence: high.

## Iteration: Answer To Concept Drafts

- did: Generated deterministic concept update drafts from answer candidates without modifying concept pages.
- why: The system needed an intermediate reviewable structure before any answer-derived concept write.
- result: Draft tests cover existing concept update drafts, new concept candidate drafts, skipped malformed/no-evidence answers, and no concept file modification during drafting.
- evidence: `wiki_tool/answer_maintenance.py`, `tests/test_answer_maintenance.py`, `tests/test_mcp_tools.py`, commit `221b0ab`.
- confidence: high.

## Iteration: Source Evidence Gate For Answer Drafts

- did: Strengthened answer-to-concept draft eligibility so only answers backed by source pages can produce concept update drafts.
- why: Concept-page-only evidence is weaker and can create circular or unsupported concept updates.
- result: Draft generation now requires evidence or used pages under `wiki/sources/` or `sources/`; concept-only evidence is skipped with a clear reason.
- evidence: `wiki_tool/answer_maintenance.py`, `tests/test_answer_maintenance.py`, commit `cbefc54`.
- confidence: high.

## Iteration: Answer-Derived Concept Maintenance Apply

- did: Connected answer-derived concept update drafts into the maintenance workflow as a conservative append-only write stage.
- why: Source-backed answer knowledge should be able to enrich existing concept pages, but only without overwriting human content or guessing on uncertain drafts.
- result: Existing concept matches with source evidence append under `## Answer-Derived Notes`, new concept candidates are skipped, duplicate application is prevented with an `answer-derived` marker, and graph/navigation/log are refreshed after applied updates.
- evidence: `wiki_tool/answer_maintenance.py`, `wiki_tool/mcp_tools.py`, `wiki_tool/agent_runtime.py`, `wiki_tool/desktop_presenter.py`, `tests/test_answer_maintenance.py`, `tests/test_agent_runtime.py`, `tests/test_mcp_tools.py`, `tests/test_desktop_gui.py`, commit `a0a8642`.
- confidence: high.

## Iteration: Answer Concept Draft Reuse

- did: Removed duplicate draft calculation by allowing `apply_answer_concept_updates()` to receive an already computed `draft_result`.
- why: Maintenance workflows already generated drafts for reporting, so applying updates should reuse that result instead of recomputing candidates and drafts.
- result: Runtime and GUI maintenance workflows now keep `answer_concept_drafts` and `answer_concept_updates` as separate result objects while passing the draft result into the apply step.
- evidence: `wiki_tool/answer_maintenance.py`, `wiki_tool/mcp_tools.py`, `wiki_tool/agent_runtime.py`, `wiki_tool/desktop_presenter.py`, `tests/test_answer_maintenance.py`, `tests/test_agent_runtime.py`, `tests/test_desktop_gui.py`, commit `abbf35a`.
- confidence: high.

## Iteration: Maintenance Answer Update Reporting

- did: Improved maintenance reporting for answer-derived concept updates with representative applied paths and skipped reason summaries.
- why: Users needed to see not only applied/skipped counts, but also which answer-to-concept updates happened and why other drafts were skipped.
- result: GUI maintenance reports can show examples such as `wiki/answers/capm.md -> wiki/concepts/capm.md`, while `log.md` keeps compact applied/skipped summary lines and preserves existing trace phrases.
- evidence: `wiki_tool/answer_maintenance.py`, `wiki_tool/desktop_presenter.py`, `tests/test_answer_maintenance.py`, `tests/test_desktop_gui.py`, commit `0ada7f3`.
- confidence: high.

## Iteration: Public Documentation Refresh

- did: Updated README and docs to describe current user domains, MCP tool surface, provider boundaries, PySide6 GUI, automatic answer saving, answer maintenance candidates, and answer-derived concept update policy.
- why: The implementation had moved beyond the older docs, and public repo users needed an accurate product-style explanation rather than stale implementation notes.
- result: The docs now distinguish sample domains from private `user_domains/`, describe Codex-first provider behavior, note Gemini as skeleton-only, and document source-evidence-gated `Answer-Derived Notes`.
- evidence: `README.md`, `docs/domain.md`, `docs/agent-spec.md`, `docs/decision-rounds.md`, `docs/prd.md`, `docs/journal.md`.
- confidence: high.

## Verification Pattern

- did: Repeatedly verified feature work with unit tests, compile checks, and sample finance wiki lint.
- why: The project touches generated files, provider paths, GUI flows, and MCP tools, so each change needs regression coverage.
- result: Recent completed implementation iterations report passing `python -m unittest discover -v`, `python -m compileall scripts wiki_tool tests`, and `python scripts\lint_wiki.py --domain examples\finance\domain.yml`.
- evidence: recent implementation outputs, `tests/`, `scripts/lint_wiki.py`.
- confidence: medium.
