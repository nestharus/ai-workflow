# Intent Agent architecture

## 1) Intent Agent architecture

### 1.1 Role and hard authority boundary

**Intent Agent** is the only user-facing interface. It mediates all interaction for the entire
lifecycle.

**Planner** is the single constraint and decision authority.

This boundary is non-negotiable:

* **Intent Agent may persist**:

  * Question queue state (open/closed/stale)
  * `question_id → canonical_key` mapping (for dedup/reassessment)
  * User-facing framing metadata (problem frame, concept map, scope)
  * Answer provenance (raw user answers and what question they answered)
  * Skeleton revision state

* **Intent Agent must not own or write**:

  * Constraint objects (authoritative or hypothetical)
  * Tradeoff positions as decision records
  * Any "final" planning decisions

Instead:

* Intent Agent produces an **AnswerTranslation artifact** (a projection of user input).
* Planner ingests that artifact, validates it, decides what becomes authoritative, and writes to
  **ConstraintsStore** / decision records.
* Intent Agent **observes** what Planner wrote (via store-change signals/watermarks) and updates
  the question queue.

### 1.2 Component model

**Deterministic orchestrator + LLM strategies**, with progressive gates.

#### IntentAgentOrchestrator (deterministic)

* Event loop: handles user messages + internal question signals + store-change signals.
* Maintains queue ordering, deduplication, staleness, batching.
* Calls LLM strategies for interpretation/rewriting only.
* Persists session state and event log.

#### LLM strategies (pluggable, bounded responsibilities)

* `IntentFrameStrategy`: update problem frame from user text.
* `ConceptMapStrategy`: maintain mapping between user terms and normalized concepts.
* `QuestionDraftStrategy`: convert internal question signals into user-facing question drafts
  (constraint-level).
* `QualityValidatorStrategy`: enforce question quality gate (pass/fail + reasons).
* `QuestionRepairStrategy`: repair failed drafts (up to 2 retries).
* `AnswerTranslateStrategy`: convert a user answer into an AnswerTranslation artifact
  (non-authoritative).
* `QueueReassessStrategy`: re-evaluate pending questions after Planner writes
  constraints/decisions.
* `SkeletonSynthesisStrategy`: produce pre-decomposition skeleton artifacts
  (workflows/entities/interfaces).

### 1.3 Intent Agent state model (corrected)

Intent Agent state is **user-interface state**, not constraint authority.

#### Persistent artifacts

* Snapshot: `.pdd_runs/<run_id>/intent/session_state.json`
* Append-only log: `.pdd_runs/<run_id>/intent/events.jsonl`
* Queue snapshot: `.pdd_runs/<run_id>/intent/question_queue.json`
* Raw answers: `.pdd_runs/<run_id>/intent/answers.jsonl`
* Answer translations (projection to Planner):
  `.pdd_runs/<run_id>/intent/answer_translations/<translation_id>.json`
* Skeleton outputs: `.pdd_runs/<run_id>/intent/skeleton/...`

#### State includes

* Problem frame + scope
* Concept map + allowed vocabulary (user-introduced terms)
* Queue state + `question_id → canonical_key` map
* Answer provenance (raw answers + which translation was produced)
* Watermarks to observe:

  * new internal question signals
  * Planner constraint/decision updates (via signals or store revision)

#### JSON Schema: IntentSessionState

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://spec-manager.local/schemas/IntentSessionState.schema.json",
  "title": "IntentSessionState",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "version",
    "run_id",
    "session_id",
    "phase",
    "original_intent",
    "problem_frame",
    "concept_map",
    "question_queue_state",
    "question_key_map",
    "answer_provenance",
    "skeleton_state",
    "watermarks"
  ],
  "properties": {
    "version": { "type": "integer", "minimum": 1 },
    "run_id": { "type": "string", "minLength": 1 },
    "session_id": { "type": "string", "minLength": 1 },

    "phase": {
      "type": "string",
      "enum": ["INTAKE", "EXECUTION"]
    },

    "original_intent": {
      "type": "object",
      "additionalProperties": false,
      "required": ["user_statement", "captured_at"],
      "properties": {
        "user_statement": { "type": "string" },
        "captured_at": { "type": "string", "format": "date-time" }
      }
    },

    "problem_frame": {
      "type": "object",
      "additionalProperties": false,
      "required": ["current_restatement", "goals", "non_goals", "scope", "success_metrics"],
      "properties": {
        "current_restatement": { "type": "string" },
        "goals": { "type": "array", "items": { "type": "string" } },
        "non_goals": { "type": "array", "items": { "type": "string" } },
        "scope": {
          "type": "object",
          "additionalProperties": false,
          "required": ["in", "out"],
          "properties": {
            "in": { "type": "array", "items": { "type": "string" } },
            "out": { "type": "array", "items": { "type": "string" } }
          }
        },
        "success_metrics": { "type": "array", "items": { "type": "string" } },
        "risk_flags": { "type": "array", "items": { "type": "string" } },

        "frame_assumptions": {
          "type": "array",
          "description": "Non-authoritative framing assumptions (not constraints).",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["text", "status", "source", "created_at"],
            "properties": {
              "text": { "type": "string" },
              "status": { "type": "string", "enum": ["HYPOTHESIS", "CONFIRMED", "REJECTED"] },
              "source": { "type": "string", "enum": ["user", "intent_agent"] },
              "created_at": { "type": "string", "format": "date-time" }
            }
          }
        }
      }
    },

    "concept_map": {
      "type": "object",
      "additionalProperties": false,
      "required": ["user_terms", "normalized_terms", "user_introduced_terms"],
      "properties": {
        "user_terms": {
          "type": "object",
          "additionalProperties": {
            "type": "object",
            "additionalProperties": false,
            "required": ["maps_to", "confidence"],
            "properties": {
              "maps_to": { "type": "array", "items": { "type": "string" } },
              "confidence": { "type": "number", "minimum": 0, "maximum": 1 }
            }
          }
        },
        "normalized_terms": {
          "type": "object",
          "additionalProperties": {
            "type": "object",
            "additionalProperties": false,
            "required": ["user_phrases"],
            "properties": {
              "user_phrases": { "type": "array", "items": { "type": "string" } }
            }
          }
        },
        "user_introduced_terms": {
          "type": "array",
          "description": "Vocabulary terms the user has used; technical terms are only allowed in questions if present here.",
          "items": { "type": "string" }
        }
      }
    },

    "question_queue_state": {
      "type": "object",
      "additionalProperties": false,
      "required": ["open_ids", "closed_ids", "stale_ids", "last_presented_question_id"],
      "properties": {
        "open_ids": { "type": "array", "items": { "type": "string" } },
        "closed_ids": { "type": "array", "items": { "type": "string" } },
        "stale_ids": { "type": "array", "items": { "type": "string" } },
        "last_presented_question_id": { "type": "string" },
        "active_batch_id": { "type": "string" }
      }
    },

    "question_key_map": {
      "type": "object",
      "description": "Intent Agent-owned references (not constraint objects).",
      "additionalProperties": {
        "type": "object",
        "additionalProperties": false,
        "required": ["canonical_key"],
        "properties": {
          "canonical_key": { "type": "string" },
          "planner_constraint_ids": { "type": "array", "items": { "type": "string" } },
          "planner_decision_ids": { "type": "array", "items": { "type": "string" } }
        }
      }
    },

    "answer_provenance": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["answer_id", "question_id", "raw_text", "created_at"],
        "properties": {
          "answer_id": { "type": "string" },
          "question_id": { "type": "string" },
          "raw_text": { "type": "string" },
          "created_at": { "type": "string", "format": "date-time" },
          "answer_translation_ref": { "type": "string" },
          "planner_ingest_trace_id": { "type": "string" }
        }
      }
    },

    "skeleton_state": {
      "type": "object",
      "additionalProperties": false,
      "required": ["revision", "structure_kind", "artifact_paths", "last_generated_at"],
      "properties": {
        "revision": { "type": "integer", "minimum": 0 },
        "structure_kind": {
          "type": "string",
          "enum": ["PRE_DECOMPOSITION", "PHASE0_LIBRARIES"]
        },
        "artifact_paths": { "type": "array", "items": { "type": "string" } },
        "last_generated_at": { "type": "string", "format": "date-time" }
      }
    },

    "watermarks": {
      "type": "object",
      "additionalProperties": false,
      "required": ["user_question_signal_watermark", "planner_update_watermark"],
      "properties": {
        "user_question_signal_watermark": { "type": "string" },
        "planner_update_watermark": { "type": "string" }
      }
    }
  }
}
```

### 1.4 Persistence and resumption

Resumption is deterministic:

1. Load `session_state.json`.
2. Read any new **UserQuestionSignals** since `user_question_signal_watermark`.
3. Read any new **Planner update signals** (constraint/decision saved events) since
   `planner_update_watermark`.
4. Recompute queue ordering and staleness.
5. Present the next question.

### 1.5 Relationship to Planner and pipeline (clarified)

#### Planner owns

* Constraint lifecycle (collection → enrichment → authority decision → propagation)
* Decision authority policy
* Writing to `ConstraintsStore`
* Writing decision records (tradeoffs, architecture choices)
* Emitting store-update signals

#### Intent Agent owns

* User interaction and question quality enforcement
* Translating user answers into **AnswerTranslation** artifacts
* Submitting AnswerTranslations to Planner
* Observing Planner outputs and updating queue state/skeletons accordingly

**Answer flow is Planner-mediated** (details in Section 4).

---

## 2) Question queue design

### 2.1 QuestionItem model and hard quality gate fields

Queue items represent **underlying unknowns** in user-facing taxonomy types (Section 5.4).
Internal-only questions never enter the user queue directly.

A question only enters the user queue if it:

* is classified as one of the 5 valid user-facing types, and
* passes the **mandatory quality gate** (Section 5.5)

#### JSON Schema: QuestionItem (with quality gate fields)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://spec-manager.local/schemas/QuestionItem.schema.json",
  "title": "QuestionItem",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "question_id",
    "status",
    "taxonomy_type",
    "scope_kind",
    "canonical_key",
    "user_prompt",
    "origins",
    "blockers",
    "priority",
    "quality_gate",
    "timestamps"
  ],
  "properties": {
    "question_id": { "type": "string", "minLength": 1 },

    "status": {
      "type": "string",
      "enum": ["OPEN", "ANSWERED", "STALE", "SUPERSEDED", "DISMISSED", "UNASKABLE"]
    },

    "taxonomy_type": {
      "type": "string",
      "enum": ["INTENT", "CONSTRAINT", "TRADEOFF", "SCOPE", "VALIDATION"]
    },

    "scope_kind": {
      "type": "string",
      "enum": ["SYSTEM_WIDE", "FEATURE_SPECIFIC"]
    },

    "canonical_key": {
      "type": "string",
      "description": "Stable key for dedup/reassessment. Reference only; not a constraint object."
    },

    "user_prompt": {
      "type": "object",
      "additionalProperties": false,
      "required": ["text", "scenario", "why_it_matters", "answer_spec"],
      "properties": {
        "text": { "type": "string" },
        "scenario": {
          "type": "string",
          "description": "Concrete scenario grounding the question."
        },
        "why_it_matters": { "type": "string" },

        "answer_spec": {
          "type": "object",
          "additionalProperties": false,
          "required": ["kind"],
          "properties": {
            "kind": {
              "type": "string",
              "enum": ["choice", "yes_no", "value", "bounded_text"]
            },
            "choices": {
              "type": "array",
              "items": {
                "type": "object",
                "additionalProperties": false,
                "required": ["id", "label"],
                "properties": {
                  "id": { "type": "string" },
                  "label": { "type": "string" }
                }
              }
            },
            "value_type": {
              "type": "string",
              "enum": ["integer", "number", "currency", "duration", "date", "string"]
            },
            "units_hint": { "type": "string" },
            "text_bounds": {
              "type": "object",
              "additionalProperties": false,
              "properties": {
                "max_items": { "type": "integer", "minimum": 1 },
                "max_chars": { "type": "integer", "minimum": 1 }
              }
            }
          }
        }
      }
    },

    "system_binding": {
      "type": "object",
      "additionalProperties": true,
      "properties": {
        "constraint_key_hints": { "type": "array", "items": { "type": "string" } },
        "decision_requirement_ids": { "type": "array", "items": { "type": "string" } },
        "work_items": { "type": "array", "items": { "type": "string" } }
      }
    },

    "origins": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["source_kind", "created_at"],
        "properties": {
          "source_kind": {
            "type": "string",
            "enum": ["PLANNER", "UNDER_SPEC", "PROMOTION_LOOP", "PDD_LIFECYCLE", "INTENT_AGENT", "SLICE_AGENT"]
          },
          "trace_id": { "type": "string" },
          "signal_id": { "type": "string" },
          "slice_id": { "type": "string" },
          "layer": { "type": "string" },
          "created_at": { "type": "string", "format": "date-time" },

          "spec_refs": {
            "type": "array",
            "items": {
              "type": "object",
              "additionalProperties": false,
              "properties": {
                "spec_text": { "type": "string" },
                "source_file": { "type": "string" },
                "source_line_hint": { "type": "integer" }
              }
            }
          },

          "code_refs": {
            "type": "array",
            "items": {
              "type": "object",
              "additionalProperties": false,
              "properties": {
                "file": { "type": "string" },
                "symbol": { "type": "string" },
                "line": { "type": "integer" }
              }
            }
          }
        }
      }
    },

    "blockers": {
      "type": "object",
      "additionalProperties": false,
      "required": ["severity", "blocked_slices"],
      "properties": {
        "severity": {
          "type": "string",
          "enum": ["BLOCKING", "HIGH_RISK", "MEDIUM_RISK", "INFO"]
        },
        "blocked_slices": { "type": "array", "items": { "type": "string" } },
        "blocked_layers": { "type": "array", "items": { "type": "string" } },
        "blocked_steps": { "type": "array", "items": { "type": "string" } }
      }
    },

    "priority": {
      "type": "object",
      "additionalProperties": false,
      "required": ["score", "explanation"],
      "properties": {
        "score": { "type": "number", "minimum": 0, "maximum": 1 },
        "explanation": { "type": "string" }
      }
    },

    "quality_gate": {
      "type": "object",
      "additionalProperties": false,
      "required": ["status", "attempts", "last_quality_record_id", "last_checked_at"],
      "properties": {
        "status": { "type": "string", "enum": ["PASS", "FAIL", "PENDING"] },
        "attempts": { "type": "integer", "minimum": 0 },
        "last_quality_record_id": { "type": "string" },
        "last_checked_at": { "type": "string", "format": "date-time" }
      }
    },

    "timestamps": {
      "type": "object",
      "additionalProperties": false,
      "required": ["created_at", "updated_at"],
      "properties": {
        "created_at": { "type": "string", "format": "date-time" },
        "updated_at": { "type": "string", "format": "date-time" }
      }
    }
  }
}
```

### 2.2 Priority model

Priority is a deterministic base score + optional LLM tie-break for top-K.

Deterministic features:

* number of blocked slices (more blocks → higher)
* severity (BLOCKING > HIGH_RISK > MEDIUM_RISK > INFO)
* scope kind (SYSTEM_WIDE > FEATURE_SPECIFIC)
* layer/stage criticality (planning-level blockers > late-stage style issues)
* staleness penalty (no remaining blockers → downrank)

LLM tie-break (top 5 only):

* "Which question unlocks the most progress with the least user burden?"

### 2.3 Reassessment algorithm (after Planner applies answers)

Reassessment is triggered by **Planner update signals** (constraint saved / decision recorded),
not by the Intent Agent writing constraints.

Steps:

1. Receive Planner update signal(s) (or observe store revision change).
2. Mechanical pass:

   * If a question's `canonical_key` is now mapped to one or more `planner_constraint_ids`,
     mark `ANSWERED`.
   * If all blockers cleared and severity is not HIGH_RISK, mark `STALE`.
3. LLM reassess pass (only for remaining OPEN where ambiguity remains):

   * Determine KEEP vs STALE vs SUPERSEDED vs REWORD based on updated frame and new
     authoritative store references.
4. Apply actions, persist `QueueReassessResult`, update `question_key_map` references.

#### JSON Schema: QueueReassessResult

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://spec-manager.local/schemas/QueueReassessResult.schema.json",
  "title": "QueueReassessResult",
  "type": "object",
  "additionalProperties": false,
  "required": ["version", "run_id", "session_id", "trigger", "created_at", "actions"],
  "properties": {
    "version": { "type": "integer", "minimum": 1 },
    "run_id": { "type": "string" },
    "session_id": { "type": "string" },

    "trigger": {
      "type": "object",
      "additionalProperties": false,
      "required": ["kind", "ref"],
      "properties": {
        "kind": {
          "type": "string",
          "enum": ["PLANNER_CONSTRAINT_SAVED", "PLANNER_DECISION_RECORDED", "USER_ANSWER_INGESTED"]
        },
        "ref": {
          "type": "string",
          "description": "Signal id, constraint id, decision id, or trace id."
        }
      }
    },

    "created_at": { "type": "string", "format": "date-time" },

    "actions": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["question_id", "action", "reason"],
        "properties": {
          "question_id": { "type": "string" },
          "action": {
            "type": "string",
            "enum": ["KEEP", "ANSWERED", "STALE", "SUPERSEDED", "REWORD", "DISMISSED"]
          },
          "reason": { "type": "string" },

          "replacement": {
            "type": "object",
            "additionalProperties": false,
            "properties": {
              "new_question_id": { "type": "string" },
              "new_canonical_key": { "type": "string" },
              "new_user_prompt_text": { "type": "string" }
            }
          }
        }
      }
    }
  }
}
```

### 2.4 Deduplication

Dedup is driven by `canonical_key` + semantic equivalence.

Dedup tiers:

1. Same canonical_key → merge origins/blockers; keep best prompt.
2. Same planner decision requirement id → merge.
3. Semantic match (LLM) among same taxonomy_type and same scope_kind.

Dedup never discards provenance: it merges `origins[]`.

### 2.5 Batching rules

Default: **one question per interaction**.

Batching allowed only when:

* 2–3 questions share the same domain concern and scope, and
* answering together reduces ambiguity, and
* all questions still individually pass the quality gate

Batch size limit: 3.

### 2.6 Staleness handling

A question becomes `STALE` (not deleted) when:

* no blocked slices remain and it isn't HIGH_RISK, or
* it is superseded by a confirmed problem redefinition, or
* Planner recorded a decision/constraint that makes it irrelevant

---

## 3) Signal flow from internal agents to Intent Agent

### 3.1 UserQuestionSignal type

Internal agents never talk to the user. They emit **UserQuestionSignal** events that request
user input.

This is a projection across the boundary:

* internal context can be included for traceability
* the final user prompt is produced by Intent Agent and must pass the quality gate

#### JSON Schema: UserQuestionSignal

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://spec-manager.local/schemas/UserQuestionSignal.schema.json",
  "title": "UserQuestionSignal",
  "type": "object",
  "additionalProperties": false,
  "required": ["uq_version", "uq_id", "run_id", "created_at", "source", "question", "context"],
  "properties": {
    "uq_version": { "type": "integer", "minimum": 1 },
    "uq_id": { "type": "string", "minLength": 1 },
    "run_id": { "type": "string", "minLength": 1 },
    "created_at": { "type": "string", "format": "date-time" },

    "source": {
      "type": "object",
      "additionalProperties": false,
      "required": ["kind"],
      "properties": {
        "kind": {
          "type": "string",
          "enum": ["PLANNER", "UNDER_SPEC", "PROMOTION_LOOP", "PDD_LIFECYCLE", "SLICE_AGENT"]
        },
        "trace_id": { "type": "string" },
        "slice_id": { "type": "string" },
        "layer": { "type": "string" },
        "signal_id": { "type": "string" }
      }
    },

    "question": {
      "type": "object",
      "additionalProperties": false,
      "required": ["text"],
      "properties": {
        "text": {
          "type": "string",
          "description": "Internal draft question text; may be technical."
        },

        "taxonomy_hint": {
          "type": "string",
          "description": "May include internal-only types; Intent Agent must reframe to user-valid types.",
          "enum": [
            "INTENT", "CONSTRAINT", "TRADEOFF", "SCOPE", "VALIDATION",
            "ARCHITECTURE", "IMPLEMENTATION", "DESIGN_PATTERN", "OPTIMIZATION",
            "UNKNOWN"
          ]
        },

        "canonical_key_hint": { "type": "string" },

        "answer_spec_hint": {
          "type": "object",
          "additionalProperties": true,
          "properties": {
            "preferred_kind": {
              "type": "string",
              "enum": ["choice", "yes_no", "value", "bounded_text"]
            },
            "choices": { "type": "array", "items": { "type": "string" } }
          }
        }
      }
    },

    "context": {
      "type": "object",
      "additionalProperties": false,
      "required": ["blocking"],
      "properties": {
        "blocking": {
          "type": "object",
          "additionalProperties": false,
          "required": ["severity", "blocked_slices"],
          "properties": {
            "severity": {
              "type": "string",
              "enum": ["BLOCKING", "HIGH_RISK", "MEDIUM_RISK", "INFO"]
            },
            "blocked_slices": { "type": "array", "items": { "type": "string" } }
          }
        },

        "spec_refs": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "properties": {
              "spec_text": { "type": "string" },
              "source_file": { "type": "string" },
              "source_line_hint": { "type": "integer" }
            }
          }
        },

        "code_refs": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "properties": {
              "file": { "type": "string" },
              "symbol": { "type": "string" },
              "line": { "type": "integer" }
            }
          }
        }
      }
    },

    "payload": {
      "type": "object",
      "description": "Extensible payload for planner-specific fields (decision requirement ids, etc.).",
      "additionalProperties": true
    }
  }
}
```

#### Storage location

* `.pdd_runs/<run_id>/coordination/user_questions.jsonl` (append-only)

### 3.2 Who emits UserQuestionSignal

#### Planner

* AuthorityDecider marks items `human_required`
* QuestionComposer produces draft questions
* Planner emits UserQuestionSignals for each human-required unknown

#### UnderSpecManager

* When ambiguity cannot be resolved automatically
* Emits UserQuestionSignals instead of running InteractiveWorkflow

#### PromotionLoop / PddLifecycle

* Lifecycle checkpoints become signals (Section 10)
* No direct `input()` calls

#### Slice agents

* Rare; only when a slice has user-domain ambiguity
* Must still be reframed into user-valid taxonomy types by Intent Agent

### 3.3 Intent Agent ingestion pipeline (signal → queued question)

Pipeline is gated:

1. **Ingest** UserQuestionSignal
2. **Classify/reframe** into user-valid taxonomy type (Section 5.4)
3. **Draft** user question with:

   * domain-language text
   * scenario
   * bounded answer_spec
4. **Quality gate** (Section 5.5)

   * PASS → create QuestionItem and enqueue
   * FAIL → repair up to 2 retries
   * FAIL after retries → mark UNASKABLE and escalate back to Planner for reformulation or
     auto-resolution (never degrade and ask anyway)

### 3.4 Immediate vs queued vs self-resolve

* **Immediate ask**: only if queue is empty or current question is INFO and new question is
  BLOCKING.
* **Queued**: default.
* **Self-resolve**: only in `--auto` mode and only for questions that:

  * do not require human authority, and
  * can be resolved by research/tools with validation, and
  * do not violate "block on ambiguity" (i.e., resolution must be supported and
    confidence-checked by Planner)

---

## 4) Answer flow from user back to agents

### 4.1 Planner-mediated answer lifecycle (required flow)

Correct flow:

```text
User answers →
Intent Agent records raw answer provenance →
Intent Agent produces AnswerTranslation artifact →
Planner ingests AnswerTranslation →
Planner validates + decides what becomes authoritative →
Planner writes to ConstraintsStore / decision record store →
Planner emits update signals →
Intent Agent observes updates → marks questions answered/reassesses queue
```

Intent Agent never writes constraints.

### 4.2 Planner ingestion and validation responsibilities

Planner ingestion step must:

* validate translation artifact schema
* validate that the proposed constraints are:

  * in a user-valid taxonomy space (constraint/tradeoff/scope/validation/intent), and
  * consistent with existing authoritative constraints (or produce conflict resolution questions)
* apply authority policy:

  * user answers are authoritative inputs
  * planner-derived enrichments are non-authoritative unless sourced
* write accepted constraints into **ConstraintsStore**
* write decisions into a **DecisionRecordStore** (tradeoffs/architecture outcomes)
* emit update signals:

  * `constraint_saved`
  * `decision_recorded`

Intent Agent uses these signals to close questions.

### 4.3 AnswerTranslate recursion guard (mandatory)

`AnswerTranslateStrategy` may propose follow-up questions, but:

* Follow-ups must pass the **same quality gate** as all other questions.
* Recursion cap:

  * **max 2 follow-up questions per user answer** (across the full reassessment cycle)
* Follow-ups that fail quality gate after retries:

  * are routed to Planner for auto-resolution or reformulation
  * are not surfaced to the user as degraded questions

### 4.4 AnswerTranslation artifact

This artifact is a boundary projection: **non-authoritative**.

#### JSON Schema: AnswerTranslation

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://spec-manager.local/schemas/AnswerTranslation.schema.json",
  "title": "AnswerTranslation",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "version",
    "translation_id",
    "run_id",
    "session_id",
    "question_id",
    "answer_id",
    "created_at",
    "user_answer",
    "extracted",
    "recursion_budget",
    "provenance"
  ],
  "properties": {
    "version": { "type": "integer", "minimum": 1 },
    "translation_id": { "type": "string" },
    "run_id": { "type": "string" },
    "session_id": { "type": "string" },
    "question_id": { "type": "string" },
    "answer_id": { "type": "string" },
    "created_at": { "type": "string", "format": "date-time" },

    "user_answer": {
      "type": "object",
      "additionalProperties": false,
      "required": ["raw_text"],
      "properties": {
        "raw_text": { "type": "string" },
        "selected_choice_id": { "type": "string" },
        "parsed_values": { "type": "object", "additionalProperties": true }
      }
    },

    "extracted": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "constraint_candidates",
        "scope_candidates",
        "tradeoff_candidates",
        "validation_candidates",
        "followup_question_drafts"
      ],
      "properties": {
        "constraint_candidates": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": [
              "canonical_key_hint",
              "question",
              "answer",
              "scope_kind",
              "confidence"
            ],
            "properties": {
              "canonical_key_hint": { "type": "string" },
              "question": {
                "type": "string",
                "description": "Proposed constraint question (domain language)."
              },
              "answer": {
                "type": "string",
                "description": "Proposed constraint answer (domain language)."
              },
              "scope_kind": {
                "type": "string",
                "enum": ["SYSTEM_WIDE", "FEATURE_SPECIFIC"]
              },
              "target_slice_id": { "type": "string" },
              "confidence": { "type": "number", "minimum": 0, "maximum": 1 },
              "rationale": { "type": "string" }
            }
          }
        },

        "scope_candidates": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["in", "out"],
            "properties": {
              "in": { "type": "array", "items": { "type": "string" } },
              "out": { "type": "array", "items": { "type": "string" } }
            }
          }
        },

        "tradeoff_candidates": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["axis", "preference", "confidence"],
            "properties": {
              "axis": {
                "type": "string",
                "description": "Domain-level tradeoff axis (no implementation terms)."
              },
              "preference": {
                "type": "string",
                "description": "User preference phrased as a priority."
              },
              "confidence": { "type": "number", "minimum": 0, "maximum": 1 }
            }
          }
        },

        "validation_candidates": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["acceptance_statement"],
            "properties": {
              "acceptance_statement": { "type": "string" }
            }
          }
        },

        "followup_question_drafts": {
          "type": "array",
          "description": "Draft follow-ups; must pass the same quality gate before enqueue.",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": [
              "draft_id",
              "taxonomy_type",
              "canonical_key_hint",
              "text",
              "scenario",
              "answer_spec"
            ],
            "properties": {
              "draft_id": { "type": "string" },
              "taxonomy_type": {
                "type": "string",
                "enum": ["INTENT", "CONSTRAINT", "TRADEOFF", "SCOPE", "VALIDATION"]
              },
              "canonical_key_hint": { "type": "string" },
              "text": { "type": "string" },
              "scenario": { "type": "string" },
              "answer_spec": {
                "type": "object",
                "additionalProperties": false,
                "required": ["kind"],
                "properties": {
                  "kind": {
                    "type": "string",
                    "enum": ["choice", "yes_no", "value", "bounded_text"]
                  },
                  "choices": { "type": "array", "items": { "type": "string" } }
                }
              }
            }
          }
        }
      }
    },

    "recursion_budget": {
      "type": "object",
      "additionalProperties": false,
      "required": ["max_followups", "used_followups"],
      "properties": {
        "max_followups": { "type": "integer", "const": 2 },
        "used_followups": { "type": "integer", "minimum": 0 }
      }
    },

    "provenance": {
      "type": "object",
      "additionalProperties": false,
      "required": ["produced_by", "model_id"],
      "properties": {
        "produced_by": { "type": "string", "enum": ["INTENT_AGENT"] },
        "model_id": { "type": "string" }
      }
    }
  }
}
```

---

## 5) Intent understanding algorithm

### 5.1 Interaction model (single agent, progressive gating)

The user talks only to the Intent Agent.

Internally, the Intent Agent behaves like:

* conversational UI to the user
* event-driven mediator to the pipeline (signals in/out)

### 5.2 Proportional depth: how intent is built incrementally

Each user message updates:

* problem frame restatement
* scope in/out
* domain terms and concept map
* candidate unknowns (as potential questions)

Then the agent chooses:

* ask **one** highest-value question, or
* produce/update the pre-decomposition skeleton if there is enough to proceed

"Enough to proceed" means:

* core workflows can be identified
* at least the major constraint dimensions have initial coverage or explicitly open questions
* no irreversible assumptions are required to start skeleton work

### 5.3 Vague input handling (no questionnaire dumps)

If user input is vague, the agent asks a single **INTENT** question that disambiguates between
plausible frames.

Example (valid INTENT question):

* **Scenario:** "Different systems use 'settlement processing' to mean different things."
* **Question:** "Which best matches what you mean by 'settlement processing' right now?"
* **Answer (choice):**

  * (A) "Confirming and recording completed movements of money/securities"
  * (B) "Matching trades/instructions and resolving breaks"
  * (C) "Reconciling internal records against external counterparties"
  * (D) "Something else (describe in 1–2 sentences)"

This is bounded, scenario-grounded, and domain-answerable.

### 5.4 Question taxonomy (valid vs prohibited)

All questions are classified into **exactly one** of these types.

#### 5.4.1 Valid user-facing question types (ONLY these reach the user)

| Type | What it asks | Answer form | Example |
| --- | --- | --- | --- |
| **INTENT** | Solved term meaning | choice/text | Ambig terms |
| **CONSTRAINT** | Boundaries, limits | value/choice/yes | Explicit limits |
| **TRADEOFF** | Priority conflict | choice | Conflicting goals |
| **SCOPE** | In/out timing | choice/yes | Phases |
| **VALIDATION** | Correctness judged | text/choice | Acceptance rules |

**Examples:**

* INTENT: "When you say 'X', do you mean A, B, or C?"
* CONSTRAINT: "If a record is corrected, must we keep the original?"
* TRADEOFF: "Fast response or avoid partial results?"
* SCOPE: "Is feature X required now or can it be added later?"
* VALIDATION: "Provide one example flow and what counts as 'done'."

#### 5.4.2 Prohibited internal-only question types (NEVER reach the user directly)

These types may appear in UserQuestionSignals as hints, but must be reframed into valid types
before user exposure.

| Internal-only type | Why prohibited | Reframe pattern (to a valid type) |
| --- | --- | --- |
| **ARCHITECTURE** | System design patterns not user's responsibility | Ask about behavior/timing |
| **IMPLEMENTATION** | Library choices internal unless user constrained | Ask about compat/lock-in |
| **DESIGN_PATTERN** | Code structuring is internal | Ask about change frequency |
| **OPTIMIZATION** | Performance tactics internal | Ask about performance targets |

#### Reframing examples (required)

* **Internal (ARCHITECTURE):** "Should this be event-driven or synchronous?"

  * **User-valid (CONSTRAINT):**
    **Scenario:** "After a settlement is recorded, different screens/reports may update at different
    times."
    **Question:** "After a settlement is recorded, do users need to see it updated everywhere
    immediately, or is a short delay (seconds to minutes) acceptable?"
    **Choices:** (A) Immediately everywhere, (B) Short delay is fine, (C) Depends (describe where it
    must be immediate)

* **Internal (IMPLEMENTATION):** "Which database should we use?"

  * **User-valid (CONSTRAINT/SCOPE):**
    **Scenario:** "Some organizations have platform commitments that constrain where data can live."
    **Question:** "Do you have an existing platform commitment for where this data must live (for
    example, an approved vendor or on‑prem requirement), or is this a new decision?"
    **Choices:** (A) Existing commitment, (B) New decision, (C) Not sure yet

* **Internal (OPTIMIZATION):** "Should we add caching?"

  * **User-valid (CONSTRAINT):**
    **Scenario:** "Some screens can show slightly out-of-date values if it makes them faster."
    **Question:** "For user-facing balances and totals, is it acceptable if the displayed value is
    briefly out of date (for example, up to 30 seconds) to keep the system responsive?"
    **Choices:** (A) No, must be current, (B) Yes, brief delay OK, (C) Depends by screen

### 5.4.3 System-wide vs feature-specific

Every question and its canonical key must be tagged as:

* **SYSTEM_WIDE**: affects multiple workflows/slices (asked earlier, higher priority)
* **FEATURE_SPECIFIC**: only affects a specific workflow (asked when that workflow is planned)

### 5.4.4 Constraint dimension list (for CONSTRAINT questions)

CONSTRAINT questions must map to one (or more) of these dimensions:

* **Operational**: latency, throughput, availability, RTO/RPO, batch windows
* **Regulatory**: compliance regimes, audit requirements, data residency
* **Organizational**: team size, expertise, operational ownership, support hours
* **Legal/Licensing**: open-source policy, vendor restrictions, contractual constraints
* **Financial**: budget ceilings, cost targets, cost sensitivity to volume
* **Platform**: existing cloud/on‑prem commitments, network constraints, identity provider constraints
* **Data**: sensitivity, retention, volume estimates, lineage requirements, access controls

### 5.5 Question quality gate (hard enforcement)

Every user-facing question must pass **all five** rules.

#### 5.5.1 The five rules (pass/fail)

1. Domain language only

   * Answerable by a business-domain expert who has never written code
   * No architecture jargon, implementation jargon, framework names
   * Exception: if the user introduced a technical term, it may be used (tracked in
     `concept_map.user_introduced_terms`)

2. Bounded answerability

   * Must have a concrete answer space:

     * choice set (preferred)
     * yes/no
     * concrete value (number/date/duration/etc.)
     * bounded_text (explicit bounds like "up to 3 items")
   * No open-ended "what do you think about…"

3. Specific behavior or property

   * Must reference a concrete behavior/outcome/property
   * Avoid abstract dimensions ("consistency", "scalability") unless immediately grounded in
     observable behavior

4. Scenario grounded

   * Must include a scenario or a failure mode that explains why it matters

5. One question per interaction (default)

   * One atomic decision per QuestionItem
   * Batching only per Section 2.5 and still must pass this rule at the batch level

#### 5.5.2 Enforcement pipeline

```text
QuestionDraftStrategy produces candidate →
QualityValidatorStrategy evaluates →
PASS: enqueue
FAIL: QuestionRepairStrategy retries (max 2) →
FAIL after retries: mark UNASKABLE + escalate to Planner (reformulate or auto-resolve)
```

All attempts are logged as QualityCheckRecords in the event log.

#### JSON Schema: QualityCheckRecord

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://spec-manager.local/schemas/QualityCheckRecord.schema.json",
  "title": "QualityCheckRecord",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "record_id",
    "question_id",
    "attempt",
    "created_at",
    "candidate",
    "checks",
    "result",
    "reason",
    "validator_version"
  ],
  "properties": {
    "record_id": { "type": "string" },
    "question_id": { "type": "string" },
    "attempt": { "type": "integer", "minimum": 1 },
    "created_at": { "type": "string", "format": "date-time" },

    "candidate": {
      "type": "object",
      "additionalProperties": false,
      "required": ["text", "scenario", "answer_spec_kind", "taxonomy_type"],
      "properties": {
        "text": { "type": "string" },
        "scenario": { "type": "string" },
        "answer_spec_kind": {
          "type": "string",
          "enum": ["choice", "yes_no", "value", "bounded_text"]
        },
        "taxonomy_type": {
          "type": "string",
          "enum": ["INTENT", "CONSTRAINT", "TRADEOFF", "SCOPE", "VALIDATION"]
        }
      }
    },

    "checks": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "domain_language_only",
        "bounded_answerability",
        "specific_behavior",
        "scenario_grounded",
        "single_question"
      ],
      "properties": {
        "domain_language_only": { "type": "boolean" },
        "bounded_answerability": { "type": "boolean" },
        "specific_behavior": { "type": "boolean" },
        "scenario_grounded": { "type": "boolean" },
        "single_question": { "type": "boolean" }
      }
    },

    "result": { "type": "string", "enum": ["PASS", "FAIL"] },
    "reason": {
      "type": "string",
      "description": "Short explanation of failure or confirmation."
    },
    "validator_version": { "type": "string" }
  }
}
```

#### Example quality record (illustrative)

```json
{
  "record_id": "qc_01",
  "question_id": "q_123",
  "attempt": 1,
  "created_at": "2026-02-13T10:12:00Z",
  "candidate": {
    "text": "Do you require eventual consistency for transaction records?",
    "scenario": "Different parts of the system may update at different times.",
    "answer_spec_kind": "choice",
    "taxonomy_type": "CONSTRAINT"
  },
  "checks": {
    "domain_language_only": false,
    "bounded_answerability": true,
    "specific_behavior": false,
    "scenario_grounded": false,
    "single_question": true
  },
  "result": "FAIL",
  "reason": "Uses architecture jargon and does not describe an observable business behavior.",
  "validator_version": "qv_1.0"
}
```

### 5.6 BAD → GOOD correction table (required)

All "GOOD" examples below satisfy the five rules.

**BAD → GOOD corrections:**

1. **BAD:** "For transaction records, do you require strong consistency or eventual consistency?"

   **GOOD:**
   Scenario: "After a settlement is recorded, different screens/reports may update at different times."
   Question: "After a settlement is recorded, do users need to see it reflected everywhere
   immediately, or is a short delay (seconds to minutes) acceptable?"
   Choices: (A) Immediate everywhere, (B) Short delay OK, (C) Depends (where must be immediate?)

2. **BAD:** "Should this run event-driven, batch, or synchronous?"

   **GOOD:**
   Scenario: "Some organizations process settlements as they arrive; others process them in scheduled runs."
   Question: "Should settlements be processed as they arrive throughout the day, or collected and processed
   at scheduled times (for example, end of day)?"
   Choices: (A) As they arrive, (B) Scheduled runs, (C) Both (explain which are immediate)

3. **BAD:** "What is the minimum acceptable behavior for this flow?"

   **GOOD:**
   Scenario: "Sometimes a settlement completes internally but the confirmation to the counterparty fails."
   Question: "If a settlement completes internally but the confirmation to the counterparty fails,
   what should happen next?"
   Choices: (A) Retry automatically, (B) Pause and alert a human, (C) Proceed but flag for manual follow-up

4. **BAD:** "Should external integrations be plug-in points or hardwired?"

   **GOOD:**
   Scenario: "Some systems must be able to switch providers later."
   Question: "If this system connects to an external clearing house or data provider, do you expect
   the provider to be fixed long-term or possibly change?"
   Choices: (A) Fixed provider, (B) Provider may change, (C) Not sure yet

5. **BAD:** "Should we use WebSockets or polling for real-time updates?"

   **GOOD:**
   Scenario: "Users may need near-real-time status updates."
   Question: "When a settlement status changes, how quickly do users need to see the update?"
   Choices: (A) Within a few seconds, (B) Within a few minutes is fine, (C) Only needs to update on refresh

6. **BAD:** "Which database should we use for the ledger?"

   **GOOD:**
   Scenario: "Some organizations restrict what vendors can be used."
   Question: "Are there vendor or platform restrictions that limit which storage technologies are
   allowed (approved vendor list, on‑prem requirement, etc.), or is this open?"
   Choices: (A) Restricted (describe), (B) Open, (C) Not sure

7. **BAD:** "Should we use caching to improve performance?"

   **GOOD:**
   Scenario: "Some values can be slightly delayed if it makes the system responsive."
   Question: "For user-visible balances, is it acceptable if the displayed value is briefly out of
   date (for example, up to 30 seconds)?"
   Choices: (A) No, must be current, (B) Yes, brief delay OK, (C) Depends (which screens?)

### 5.7 When to produce the initial skeleton

Produce a pre-decomposition skeleton when:

* there is a stable restatement of the problem frame (even if marked "tentative")
* core workflows are identifiable
* major constraint dimensions have either:

  * at least one answered constraint, or
  * an explicit queued question (not silent assumptions)

Skeleton creation is incremental; it is revised as constraints arrive.

---

## 6) Skeleton format and depth

### 6.1 Output artifacts and directory structure (pre-decomposition)

For intent-level intake, the Intent Agent must **not invent library boundaries**.

#### Skeleton structure

```text
system/
  intent.md
  workflows/
    <workflow>.py
  entities/
    <entity>.py
  interfaces/
    <interface>.py
analysis/intent/
  intent_snapshot.json
  question_queue.json
```

* `system/intent.md`: problem frame, scope, success metrics, open questions (IDs), and pointers
  to authoritative constraints in the constraint store (by IDs), without copying constraint
  objects.
* `workflows/*.py`: domain workflows as function/class stubs.
* `entities/*.py`: domain entities and value objects.
* `interfaces/*.py`: external boundaries (providers, counterparties, identity, reporting feeds).

### 6.2 Depth rule

"One level deeper than names":

* include workflows + key interfaces + entity shapes
* include TODOs tied to question IDs
* do not implement business logic

Example stub (TODO references the queue item, not a constraint object):

```python
# Q:q_7f3a (canonical_key: constraint.operational.visibility_delay)
# Scenario: users may need status updates immediately after recording a settlement.
# TODO: finalize acceptable status propagation delay based on user answer.

def record_settlement(settlement_instruction):
    raise NotImplementedError
```

### 6.3 Metadata snapshot (no constraint objects)

`analysis/intent/intent_snapshot.json` contains:

* problem_frame
* concept_map
* queue open question IDs + canonical keys
* references to planner-authored constraints/decisions by ID (if available)

It must not embed constraint objects.

### 6.4 Feeding the existing pipeline

* If intake is **prose**: Phase 0 runs, produces `libraries/…` outputs; Intent Agent uses those
  outputs to drive user questions and produce a skeleton view if needed.
* If intake is **intent-level**: pipeline starts from `system/` pre-decomposition skeleton; library
  decomposition occurs later (Section 8).

---

## 7) Problem redefinition protocol

### 7.1 Triggers (system-level) and user-level phrasing (quality-gated)

Triggers remain system-side:

* planner decomposes a user term into multiple subsystems that changes scope materially
* conflicts between requirements emerge
* architecture implications materially change operational expectations

But the resulting user interaction must be **domain language, scenario grounded, bounded**, and must
pass the quality gate.

Example (VALID TRADEOFF question):

* **Scenario:** "We found a tension between two requirements as currently stated."
* **Question:** "You asked for (1) immediate visibility of every recorded transaction everywhere and
  (2) processing thousands of transactions per second. Achieving both together adds substantial
  complexity. What matters more for the initial version?"
* **Choices:** (A) Immediate visibility, (B) Highest throughput, (C) Balanced (accept some delay
  to keep throughput)

### 7.2 Redefinition interaction pattern

A redefinition is handled as a single queue item:

* shows:

  * original intent statement
  * current restatement
  * what changed (1–3 bullets)
* asks for bounded confirmation:

  * (A) yes, adopt new restatement
  * (B) no, keep original framing
  * (C) partial (specify what changes)

This becomes authoritative only after Planner ingests the AnswerTranslation and writes the
scope/constraint updates.

### 7.3 Preventing drift

Maintain "alignment invariants" as part of problem frame metadata:

* a short list of "must remain true" statements derived from original intent and user-confirmed
  scope
* when Planner proposes a plan that violates an invariant, it emits a TRADEOFF or SCOPE question
  for user confirmation

---

## 8) Phase 0 relationship

### 8.1 Decomposition ownership (explicit)

* **Prose intake** → Phase 0 owns decomposition:

  * sectionize → discover → route → coverage → assemble → `libraries/…`
  * Intent Agent wraps Phase 0 outputs into user questions + pre-filled framing

* **Intent-level intake** → Intent Agent produces **pre-decomposition** skeleton only:

  * `system/workflows/entities/interfaces`
  * no library boundaries invented here

Library decomposition happens later when Planner has enough constraints and stable workflow
surfaces:

* optional: run Phase 0 on `system/intent.md` + skeleton comments to propose library boundaries
* or Planner/L2 planning produces library boundaries directly, backed by constraints and evidence

### 8.2 Phase 0 as a strategy, not a parallel intake truth

Phase 0 remains an internal strategy invoked when:

* user supplies complete prose specs
* or system wants to propose library decomposition after intent-level work stabilizes

Phase 0 outputs remain authoritative evidence for routing/coverage within its scope.

---

## 9) Session persistence and resumption

### 9.1 What is saved

* Intent session snapshot (no constraints)
* Event logs:

  * user messages
  * question signals received
  * quality gate records
  * answers and translations produced
  * queue reassessment actions
* Queue snapshot
* Skeleton revisions
* Watermarks to observe new signals and Planner store updates

### 9.2 Resume behavior

On resume:

1. Show pipeline progress since last session (from planner update signals and slice status if
   available).
2. Present the next highest-priority question (or batch).
3. Keep the queue consistent: re-run reassessment against latest Planner updates.

### 9.3 Auto mode behavior (no human)

In `--auto` mode:

* Intent Agent may still generate internal questions but:

  * questions requiring human authority remain unresolved
  * Planner either blocks or makes best-effort decisions only where authority policy permits
* Intent Agent continues to enforce taxonomy and quality gate for any hypothetical "user" prompts,
  but those prompts are not emitted; they are used only to identify blocking unknowns and to
  document why work cannot proceed.

---

## 10) Integration wiring

### 10.1 New modules/files to create

Create `spec_manager/orchestration/intent_agent/`:

* `agent.py`

  * `IntentAgentOrchestrator`
* `state.py`

  * session state load/save + schemas
* `queue.py`

  * queue operations + dedup + priority + batching + reassess
* `quality_gate.py`

  * `QualityValidatorStrategy`, `QuestionRepairStrategy`, record persistence
* `taxonomy.py`

  * taxonomy classification + reframing helpers
* `signals.py`

  * read/write for `UserQuestionSignal` store
* `answer_translation.py`

  * write AnswerTranslation artifacts
* `skeleton.py`

  * pre-decomposition skeleton renderer (`system/` layout)

Add coordination stores:

* `.pdd_runs/<run_id>/coordination/user_questions.jsonl` (already specified)
* `.pdd_runs/<run_id>/coordination/planner_updates.jsonl` (constraint/decision saved signals)

### 10.2 Modify existing modules (explicit replacements)

#### A) Planner: ingest AnswerTranslation and emit updates

* Add Planner capability: `INGEST_USER_ANSWER`

  * input: path to AnswerTranslation artifact
  * output: trace id + list of written constraint ids + decision ids
* Ensure Planner is the only writer to ConstraintsStore and decision store.
* Use existing `on_constraint_saved` callback to emit update events to:

  * `.pdd_runs/<run_id>/coordination/planner_updates.jsonl`

Update event examples (not a required schema here):

* `{"kind":"constraint_saved","constraint_id":"c_...","canonical_key":"...","trace_id":"...","created_at":"..."}`
* `{"kind":"decision_recorded","decision_id":"d_...","axis":"...","trace_id":"...","created_at":"..."}`

#### B) UnderSpecManager: replace InteractiveWorkflow with UserQuestionSignals

Replace `_resolve_interactive` in `under_spec_manager.py`:

* Old behavior:

  * write `constraint_request.md`
  * run InteractiveWorkflow
  * parse constraints locally

* New behavior:

  * emit UserQuestionSignals (one per under-spec event, or dedup cluster)
  * return outcome indicating WAITING/BLOCKED (depending on lifecycle state)
  * do not write constraints

UnderSpec events that cannot be resolved automatically become queue items via Intent Agent.

#### C) PromotionLoop: block by WAITING on questions, not raw CLI prompts

In `promotion_loop.py` (CoordinateStep / under-spec handling):

* When under-spec unresolved in interactive mode:

  * emit UserQuestionSignals (via UnderSpecManager)
  * transition slice to WAITING
  * monitors/wake triggered only when Planner writes required constraints

#### D) PddLifecycle: replace human checkpoints with Intent Agent signals

All `input()` prompts must be removed from lifecycle core.

Specifically, replace these methods' behavior:

* `_request_approval` (L1 approval)
* `_request_l2_checkpoint` (L2 checkpoint)
* `_request_release_signoff` (release signoff)

They must:

* emit UserQuestionSignals of type VALIDATION / SCOPE / TRADEOFF as appropriate
* return WAITING until Planner records the user's answer outcomes

**Overview documents may still be generated** for context, but they are not the approval
mechanism.

#### E) InteractiveWorkflow: preserve only as internal tool

* InteractiveWorkflow can remain for:

  * offline refinement tooling
  * auto-mode experiments
* It must not be the user interface in interactive mode.
* In interactive mode, it should emit UserQuestionSignals instead of calling `input()`.

### 10.3 Lifecycle checkpoint replacement mapping (required)

#### Mapping table: old → new

| Method | Current | Replacement |
| --- | --- | --- |
| `_request_approval` | Shows overview, prompts `[a/f/q]` | Emit VALID signals (+ optional SCOPE) |
| `_request_l2_checkpoint` | Approve/quit w/ minimal context | Emit Planner items |
| `_resolve_interactive` | Writes `constraint_request.md` + runs | Emit signals; slice waits |
| `_request_release_signoff` | Approve/reject after scorecard | Emit VALID signoff |

#### Before/after flows (required)

##### 1) L1 approval

Before:

```text
L1 completes →
overview generated →
_request_approval() calls input() →
approve/feedback/quit (no planning context surfaced)
```

After:

```text
L1 completes →
Planner emits:
  - user questions for human-required items (if any)
  - planner_updates for constraints/decisions it recorded automatically
Intent Agent presents:
  - captured intent summary (problem frame)
  - authoritative constraints (by reference + user-friendly rendering)
  - next BLOCKING question (one at a time)
User answers →
Intent Agent writes AnswerTranslation →
Planner ingests + writes →
Intent Agent observes updates →
When no BLOCKING questions remain:
  - Intent Agent asks VALIDATION alignment question:
    "Does this summary match what you want?" (bounded choices)
Proceed to L2
```

##### 2) L2 checkpoint

Before:

```text
L2 planner runs →
_request_l2_checkpoint() asks approve/quit (no surfaced tradeoffs/authority escalations)
under_spec events may go to InteractiveWorkflow
```

After:

```text
L2 planner runs strategy pipeline →
AuthorityDecider marks human_required →
Planner emits UserQuestionSignals (TRADEOFF/CONSTRAINT/SCOPE)
Intent Agent enforces quality gate and asks them in priority order
User answers → AnswerTranslation → Planner writes
Checkpoint passes when BLOCKING human_required items resolved
Proceed to L3
```

##### 3) Under-spec interactive resolution

Before:

```text
UnderSpecManager writes constraint_request.md →
InteractiveWorkflow prompts user →
UnderSpecManager parses constraints and writes
```

After:

```text
UnderSpecManager emits UserQuestionSignals →
slice enters WAITING →
Intent Agent asks user questions (quality-gated) →
user answers → AnswerTranslation →
Planner writes constraints →
wake events fire →
slice resumes
```

##### 4) Release signoff

Before:

```text
scorecard printed →
input() approve/reject
```

After:

```text
Planner emits final validation summary signals (or artifact) →
Intent Agent asks VALIDATION signoff question:
  Scenario: "This is what was built and verified."
  Question: "Does this meet your acceptance expectations for release?"
  Choices: (A) Approve release, (B) Not yet — list up to 3 issues, (C) Approve with known gaps recorded
User answer → AnswerTranslation → Planner records decision + (if B) new questions/constraints
```

### 10.4 CLI adapter (backward compatibility)

A CLI runner may remain, but must be a thin adapter that:

* reads queued QuestionItems from the Intent Agent store
* displays them and collects user answers
* forwards answers to the Intent Agent (not to Planner directly)
* never constructs its own questions

### 10.5 Migration path (incremental)

1. Introduce UserQuestionSignal store and Intent Agent queue + quality gate.
2. Modify UnderSpecManager interactive path to emit UserQuestionSignals (no InteractiveWorkflow).
3. Add Planner capability to ingest AnswerTranslation and write constraints/decisions.
4. Add planner update signals so Intent Agent can observe authoritative writes.
5. Replace lifecycle `input()` checkpoints with signals + WAITING semantics.
6. Introduce pre-decomposition skeleton output for intent-level intake; keep Phase 0 for prose
   intake.

This produces a single coherent user interaction layer with enforced question quality, clear
authority boundaries, and lifecycle checkpoints that surface planning decisions through the same
question queue mechanism.
