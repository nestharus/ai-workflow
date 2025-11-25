# Operational Protocols

These nine protocols define required agent behavior within the orchestrator-based system.

1. **Consult the Knowledge Graph**: Before starting any task, review `docs/README.md` for
   the index and consult relevant domain documentation in `docs/product/`, `docs/ux/`,
   `docs/ui/`, `docs/tech/`, and `docs/qa/`.

2. **Adhere to Roles**: Strictly adhere to your assigned role (R1, R2, R3, R4, or R5). Do
   not deviate from your domain or function.

3. **Communication**: Use TOON (Token-Oriented Object Notation) for structured data handoffs
   (specs, plans) when required by the workflow.

4. **Orchestrator Submission**: Agents submit messages to the orchestrator via POST to
   `/api/v1/orchestrator/submit` instead of calling other agents directly.

5. **No Long-Running Operations**: Agents must not make long-running tool calls directly;
   instead, submit messages to the orchestrator to request long-running tasks.

6. **Git Worktree Usage**: Agents may work in parallel using git worktrees managed by the
   orchestrator.

7. **Execution Standards**: After performing edits, run local validation commands
   (tests/linting) as defined in the technical documentation.

8. **Documentation Edits**: Documentation updates are allowed when needed to complete tasks
   or satisfy review feedback.

9. **Review Feedback Coverage**: Address every review comment (including documentation and
   formatting). If a comment is unclear, forward it to the orchestrator instead of
   skipping it.
