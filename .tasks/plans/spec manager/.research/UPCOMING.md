# Upcoming Research Prompts

Write these AFTER the prior response. Use the actual
implementation to inform the prompt.

## 1. Planning Module Architecture — DONE (response received)

## 2. QA Eval Architecture with Planner — DONE (implemented)

* Full eval package: ground_truth, trace_loader, scorers, reporter, harness, export_gt
* Planner enhanced: override_provider, model_id, auto-persist, decision_key, index.jsonl
* 204 new tests, all passing (3063 total)
* Prompt: `.research/qa-eval-architecture/prompt.md`
* Response: `.research/qa-eval-architecture/response.md`

## 3. Scoring and Multi-Model Comparison

* Architecture quality scoring
* Code quality scoring
* Run same spec through Opus / GPT 5.3 codex xhigh / GLM independently
* LLM Judge upgrades for arch + code quality
* Artifact preservation and comparison framework
* Depends on: QA eval architecture

## 4. Model Routing Refinement (if needed)

* Refine routing based on QA eval results
* Tune which models for whichfortasks based on actual performance
* Depends on: QA eval results
