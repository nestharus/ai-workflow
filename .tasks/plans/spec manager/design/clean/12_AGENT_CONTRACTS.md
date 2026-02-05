LIBRARY: agents.contracts
VERSION: 1.0
CONSTRAINTS: [CON-0004, CON-0011, CON-0017]

DATA_SHAPES:
  - id: DS-AGENT-0001
    name: AgentDefinition
    fields:
      - {name: agent_id, type: string}
      - {name: purpose, type: string}
      - {name: input_schema, type: string|null}
      - {name: output_schema, type: string}
      - {name: max_context_chars, type: int}
      - {name: model_hint, type: string|null}
  - id: DS-AGENT-0002
    name: AgentInvocation
    fields:
      - {name: invocation_id, type: string}
      - {name: agent_id, type: string}
      - {name: inputs, type: map<string,any>}
      - {name: context_bundle_id, type: string|null}
      - {name: created_at, type: string}
  - id: DS-AGENT-0003
    name: AgentResult
    fields:
      - {name: invocation_id, type: string}
      - {name: raw_output, type: string}
      - {name: parsed_output, type: any|null}
      - {name: contract_validation, type: DS-COMP-0001}
      - {name: repaired, type: bool}
      - {name: errors, type: list<string>}

ALGORITHMS:
  - id: ALG-AGENT-0001
    name: RunAgentWithContractValidation
    inputs:
      - {name: invocation, type: DS-AGENT-0002}
      - {name: agent_def, type: DS-AGENT-0001}
    outputs:
      - {name: result, type: DS-AGENT-0003}
    invariants: [CON-0011]
    pseudocode:
      ```pseudo
      function RunAgentWithContractValidation(agent_id, input_payload, output_schema, repair_policy):
        raw = agent.run(agent_id, input_payload)
      
        verdict = schema.validate(output_schema, raw)
        if verdict.ok:
          return raw
      
        repaired = RepairInvalidAgentOutput(agent_id, input_payload, raw, verdict.errors, output_schema, repair_policy)
        if repaired.ok:
          return repaired.output
      
        fallback = AgentFallbackPolicy(agent_id, input_payload, raw, verdict.errors, output_schema, repair_policy)
        return fallback.output
      ```
  - id: ALG-AGENT-0002
    name: RepairInvalidAgentOutput
    inputs:
      - {name: invalid_result, type: DS-AGENT-0003}
      - {name: repair_agent_id, type: string}
      - {name: max_attempts, type: int}
    outputs:
      - {name: repaired_result, type: DS-AGENT-0003}
    invariants: [CON-0011]
    pseudocode:
      ```pseudo
      function RepairInvalidAgentOutput(agent_id, input_payload, raw_output, errors, output_schema, repair_policy):
        for attempt in range(1, repair_policy.max_repair_attempts + 1):
          repair_input = {
            "agent_id": agent_id,
            "input_payload": input_payload,
            "raw_output": raw_output,
            "errors": errors,
            "schema": output_schema
          }
      
          candidate = agent.run(repair_policy.repair_agent_id, repair_input)
      
          verdict = schema.validate(output_schema, candidate)
          if verdict.ok:
            return { ok: true, output: candidate }
      
          raw_output = candidate
          errors = verdict.errors
      
        return { ok: false, output: raw_output, errors: errors }
      ```
  - id: ALG-AGENT-0003
    name: AgentFallbackPolicy
    inputs:
      - {name: result, type: DS-AGENT-0003}
      - {name: fallback_modes, type: list<enum>, values: ["KEEP_RAW_AS_REMAINDER","DOWNGRADE_OUTPUT","ESCALATE_MODEL","REQUEST_HUMAN"]}
    outputs:
      - {name: next_action, type: string}
    invariants: [CON-0009]
    pseudocode:
      ```pseudo
      function AgentFallbackPolicy(agent_id, input_payload, raw_output, errors, output_schema, repair_policy):
        # 1) Quarantine on schema failure in high-risk phases
        if repair_policy.quarantine_on_invalid:
          quarantine_artifact = {
            "status": "QUARANTINED",
            "agent_id": agent_id,
            "errors": errors,
            "raw_output": raw_output
          }
          gaps.emit("GAP-SCHEMA-INVALID", evidence={ "agent_id": agent_id }, artifact=quarantine_artifact)
          return { output: quarantine_artifact }
      
        # 2) Try alternate model/agent if configured
        for fallback_agent in repair_policy.fallback_agent_ids:
          candidate = agent.run(fallback_agent, input_payload)
          verdict = schema.validate(output_schema, candidate)
          if verdict.ok:
            return { output: candidate }
      
        # 3) Hard-stop output: emit gap; return last output
        gaps.emit("GAP-AGENT-FAILED", evidence={ "agent_id": agent_id }, artifact=raw_output)
        return { output: raw_output }
      ```
