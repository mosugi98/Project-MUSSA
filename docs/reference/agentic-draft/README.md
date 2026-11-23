# Agentic draft (reference only)

`syntax_engine.py`, `orchestrator.py` and `test_syntax_engine.py` are the draft that was supplied for the agentic
SYNTAX layer. They are kept here unchanged so nothing is lost. **They are not imported or run** by MUSSA.

Why they are not used as they are:

- `syntax_engine.py` is a second SYNTAX engine. The project already has one, checked against the official calculator
  (`src/cagsyntax/scoring/`). The draft agrees on typical cases but differs from the official form: it counts every
  occluded segment x5 (officially only the first segment), takes a typed count of non-visible segments (officially
  derived from the first segment visualized beyond the occlusion), and scores answers that do not apply (such as
  aorto-ostial on segment 8) instead of reporting them. It also has no co-dominance.
- `orchestrator.py` needs `langchain-core`, `langchain-openai` and `langgraph`, imports `app.scoring...` (this
  project's package is `cagsyntax`), defaults to a 32B model, and lets the LLM fill morphology that no model measured.
- `test_syntax_engine.py`'s three scenarios are reproduced against the real engine in
  `tests/agent/test_syntax_input.py`.

Where the ideas went: `src/cagsyntax/agent/` (types and adapters over the verified engine), with perception,
deterministic reconciliation and the viewer wiring planned in `docs/superpowers/plans/2026-11-22-agent-core.md`.
An LLM reconciliation node is planned as an optional, off-by-default plug-in.
