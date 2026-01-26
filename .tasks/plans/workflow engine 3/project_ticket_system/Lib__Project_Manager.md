# Library: Project Manager (`pm`)

- **Primary responsibility**: Project-level navigation and ticket triage; minimal friction for turning planning docs into tickets.
- **Depends on**: `cli`, `wss_surfaces`, `workflow_resolver`, `indexer`
- **Out of scope**: durable schema definitions (see `Tech_Plan__Core_Infrastructure.md`).

## 1) Responsibilities (normative)

Project Manager MUST:
1. Create/select projects.
2. Import planning docs (paste or file path) into WSS.
3. Maintain a derived index for fast listing (delegates to `indexer`).
4. Infer ticket dependencies and suggested ordering (heuristic; always user-editable).
5. Provide a user surface for notifications and for workflow configuration at the project level.

## 2) WSS writes (normative)

Project Manager is a writer of:
- `workspace/projects/<project_id>/project.json`
- `workspace/tickets/<ticket_id>/ticket.json` (ticket creation path)

On any write to `project.json` or `ticket.json`, PM MUST mark the derived index dirty via `indexer` rules.

## 3) Workflow configuration surface

PM exposes project-scoped workflows by writing files under:
- `workspace/projects/<project_id>/workflows/*.yaml`

Resolution precedence and selection are defined in `workflow_resolver`.

## 4) Ticket dependency inference (heuristic, non-normative)

PM MAY propose dependency edges and ordering suggestions from:
- ticket titles/descriptions
- explicit references/IDs
- file/path overlap heuristics (if available)

All inferred dependencies MUST be editable and MUST NOT block ticket creation or execution.
