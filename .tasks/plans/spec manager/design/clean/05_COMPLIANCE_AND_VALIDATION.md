LIBRARY: compliance.validation
VERSION: 1.0
CONSTRAINTS: [CON-0011, CON-0002, CON-0009]

DATA_SHAPES:
  - id: DS-COMP-0001
    name: ContractValidationResult
    fields:
      - {name: artifact_id, type: string}
      - {name: schema_id, type: string}
      - {name: valid, type: bool}
      - {name: errors, type: list<string>}
      - {name: warnings, type: list<string>}
  - id: DS-COMP-0002
    name: ComplianceMetric
    fields:
      - {name: metric_name, type: enum, values: ["COVERAGE","TEMPLATE_COMPLIANCE","ID_UNIQUENESS","TRACE_COMPLETENESS","DRIFT_RATE","REMAINDER_RATIO","LOW_CONFIDENCE_RATE"]}
      - {name: value, type: float}
      - {name: threshold, type: float}
      - {name: severity, type: enum, values: ["INFO","WARN","ERROR"]}
      - {name: scope, type: enum, values: ["RUN","FILE","LIBRARY","ELEMENT"]}
      - {name: scope_id, type: string|null}
  - id: DS-COMP-0003
    name: ComplianceScore
    fields:
      - {name: score, type: float}
      - {name: metrics, type: list<DS-COMP-0002>}
      - {name: blockers, type: int}
      - {name: warnings, type: int}
      - {name: computed_at, type: string}
  - id: DS-COMP-0004
    name: GateDecision
    fields:
      - {name: from_phase, type: string}
      - {name: to_phase, type: string}
      - {name: decision, type: enum, values: ["PASS","WARN_PASS","BLOCK"]}
      - {name: reasons, type: list<string>}
      - {name: required_actions, type: list<string>}
  - id: DS-COMP-0005
    name: PhaseGatePolicy
    fields:
      - {name: policy_id, type: string}
      - {name: phase, type: string}
      - {name: min_score, type: float}
      - {name: max_remainder_ratio, type: float}
      - {name: max_blockers, type: int}
      - {name: allow_warn_pass, type: bool}
  - id: DS-COMP-0006
    name: ExclusionReasonCode
    fields:
      - {name: code, type: enum, values: ["FORMAT","DUPLICATE","PURE_MARKUP","OUT_OF_SCOPE","REDACTED"]}

ALGORITHMS:
  - id: ALG-COMP-0001
    name: ValidateArtifactContract
    inputs:
      - {name: artifact_json, type: string}
      - {name: schema_path, type: string}
    outputs:
      - {name: result, type: DS-COMP-0001}
    invariants: [CON-0011]
    pseudocode:
      ```pseudo
      function ValidateArtifactContract(artifact, schema_id, allowlists):
        verdict = schema.validate(schema_id, artifact)
      
        errors = []
        warnings = []
      
        if not verdict.ok:
          errors.extend(verdict.errors)
      
        signature_findings = lint.scan_for_bad_signatures(artifact, allowlists)
        errors.extend(signature_findings.errors)
        warnings.extend(signature_findings.warnings)
      
        return { ok: (len(errors) == 0), errors: errors, warnings: warnings }
      ```
  - id: ALG-COMP-0002
    name: ComputeComplianceMetrics
    inputs:
      - {name: coverage_reports, type: list<DS-PROV-0005>}
      - {name: validation_results, type: list<DS-COMP-0001>}
      - {name: drift_reports, type: list<DS-PROJ-0004>}
      - {name: risk_signals, type: list<DS-STRAT-0005>}
    outputs:
      - {name: metrics, type: list<DS-COMP-0002>}
    invariants: [INV-ACC-0101]
    pseudocode:
      ```pseudo
      function ComputeComplianceMetrics(phase_id, artifacts, coverage_report, id_registry):
        format_compliance = metric.format_compliance(artifacts)
        annotation_coverage = metric.annotation_coverage(coverage_report)
        id_normalization = metric.id_normalization(artifacts, id_registry)
      
        return {
          "format_compliance": format_compliance,
          "annotation_coverage": annotation_coverage,
          "id_normalization": id_normalization
        }
      ```
  - id: ALG-COMP-0003
    name: ComputeComplianceScore
    inputs:
      - {name: metrics, type: list<DS-COMP-0002>}
      - {name: penalties, type: map<string,float>}
    outputs:
      - {name: score, type: DS-COMP-0003}
    invariants: [CON-0009]
    pseudocode:
      ```pseudo
      function ComputeComplianceScore(metrics, findings, policy):
        score = avg([metrics.format_compliance, metrics.annotation_coverage, metrics.id_normalization])
      
        penalty = (findings.blockers * policy.blocker_penalty) + (findings.warnings * policy.warning_penalty)
        final = score - penalty
      
        return { score: score, penalty: penalty, final: final }
      ```
  - id: ALG-COMP-0004
    name: GatePhaseTransition
    inputs:
      - {name: from_phase, type: string}
      - {name: to_phase, type: string}
      - {name: score, type: DS-COMP-0003}
      - {name: policy, type: DS-COMP-0005}
    outputs:
      - {name: decision, type: DS-COMP-0004}
    invariants: [CON-0009]
    pseudocode:
      ```pseudo
      function GatePhaseTransition(phase_id, compliance_score, coverage_report, policy):
        if coverage_report.remainder_ratio > policy.max_remainder_ratio:
          gaps.emit("GAP-COVERAGE-REMAINDER", evidence=coverage_report)
          return { pass: false }
      
        if compliance_score.final < policy.compliance_threshold:
          gaps.emit("GAP-COMPLIANCE-LOW", evidence={ "phase_id": phase_id, "score": compliance_score })
          return { pass: false }
      
        if compliance_score.blockers > policy.blocker_threshold:
          gaps.emit("GAP-COMPLIANCE-BLOCKER", evidence={ "phase_id": phase_id })
          return { pass: false }
      
        return { pass: true }
      ```
  - id: ALG-COMP-0005
    name: ScanForForbiddenOutputSignatures
    inputs:
      - {name: artifact, type: object}
      - {name: allowlists, type: map<string,list<string>>}
    outputs:
      - {name: errors, type: list<string>}
      - {name: warnings, type: list<string>}
    invariants: [CON-0021]
    pseudocode:
      ```pseudo
      function ScanForForbiddenOutputSignatures(artifact, allowlists):
        errors = []
        warnings = []

        # Contract-level lint: evidence fields must contain only EVID-* values
        EVIDENCE_FIELD_PATTERN = /^EVID-F\d{4}-R\d{4}-L\d+-L\d+$/

        for field_path, value in walk_json(artifact):
          if field_path.endswith(".evidence_atom_ids[]") or field_path.endswith(".evidence_ids[]"):
            if not EVIDENCE_FIELD_PATTERN.match(value):
              if value not in allowlists.get("evidence_exceptions", []):
                errors.append(format("Invalid evidence reference at %s: %s", field_path, value))

        # Free-text warning: detect derived artifact pointers
        DERIVED_ARTIFACT_PATTERNS = [
          /runs\//,           # run workspace references
          /views\//,          # view directory references
          /\.json$/,          # JSON file references
          /\.yaml$/,          # YAML file references
          /\.md$/             # Markdown file references (unless explicitly allowed)
        ]

        for field_path, value in walk_json(artifact):
          if is_free_text_field(field_path):
            for pattern in DERIVED_ARTIFACT_PATTERNS:
              if pattern.search(value):
                if value not in allowlists.get("derived_artifact_exceptions", []):
                  warnings.append(format("Possible derived artifact reference at %s: %s", field_path, value))

        return { errors: errors, warnings: warnings }
      ```
