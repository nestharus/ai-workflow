# Upcoming Research Prompts

Write these AFTER implementing the prior response. Use the actual
implementation to inform the prompt.

## 1. Planning Module Architecture — DONE (response received)

## 2. QA Eval Architecture with Planner — DONE (prompt written)
- How to run QA with planner in the loop (interactive mode)
- Ground truth comparison methodology for planner decisions
- Scoring planner quality (accuracy, precision, epistemic hygiene)
- Using trace/replay system for debugging
- Depends on: planning module implementation
- Prompt: `.research/qa-eval-architecture/prompt.md`
- Context: `.research/qa-eval-architecture/context.zip` (17 files)

## 3. Scoring and Multi-Model Comparison
- Architecture quality scoring
- Code quality scoring
- Run same spec through Opus / GPT 5.3 codex xhigh / GLM independently
- LLM Judge upgrades for arch + code quality
- Artifact preservation and comparison framework
- Depends on: QA eval architecture

## 4. Model Routing Refinement (if needed)
- Refine routing based on QA eval results
- Tune which models for which tasks based on actual performance
- Depends on: QA eval results
