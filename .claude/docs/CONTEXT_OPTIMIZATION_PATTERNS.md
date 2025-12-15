# Context Optimization Patterns for Orchestrations

**Purpose**: Reference guide for designing efficient orchestrations and agent workflows that minimize LLM context usage while maximizing effectiveness.

**Target Audience**: Orchestrator designers, agent developers, and anyone building AI workflows.

---

## 1. Core Principles

### The Golden Rule
**LLM context is expensive and limited. Scripts are cheap and deterministic.**

### Fundamental Guidelines

1. **Use LLMs for judgment, scripts for mechanics**
   - LLMs: Strategy, categorization, ambiguous decisions, natural language understanding
   - Scripts: Sorting, filtering, formatting, file I/O, validation, aggregation

2. **Summarize data before passing between agents**
   - Never pass full files when metadata suffices
   - Extract only relevant information for next step
   - Use hierarchical summarization (details → key points → counts)

3. **Pre-compute what you can**
   - Calculate static data before orchestration begins
   - Cache intermediate results to files
   - Load on-demand rather than keeping in context

4. **Process in batches**
   - Don't invoke agents per-item for similar tasks
   - Batch similar operations, process together
   - Use pattern recognition to minimize repetition

---

## 2. Anti-Patterns to Avoid

### 2.1 Static Content in Prompts

**Problem**: Embedding configuration files, documentation, or examples directly in agent prompts.

```yaml
# ❌ BAD: Embedded in prompt
agent: plan-reviewer
prompt: |
  Review this plan against our schema:

  Schema:
    ticket_id: string (required)
    type: enum [feature, bugfix, refactor]
    tasks:
      - id: string
        description: string
        ...
  [100+ lines of schema]

  Now review: {plan_content}
```

**Solution**: Reference external files, load on demand.

```yaml
# ✅ GOOD: Reference and load
agent: plan-reviewer
prompt: |
  Review this plan against the schema at .audit/schemas/plan_schema.json

  Read the schema file, then review: {plan_content}
```

**Benefits**:
- 90% reduction in prompt tokens
- Schema changes don't require agent redeployment
- Multiple agents can share same schema
- Easier to maintain single source of truth

---

### 2.2 Algorithms in LLM Context

**Problem**: Having LLMs perform deterministic operations like sorting, filtering, or transforming data.

```python
# ❌ BAD: LLM doing algorithmic work
prompt = f"""
Given these tickets:
{json.dumps(all_tickets, indent=2)}  # 500 tickets, 50,000 tokens

Sort them by priority, then by created date.
Filter to only 'open' status.
Group by component.
Return the top 5 per component.
"""
```

**Solution**: Pre-process with scripts.

```python
# ✅ GOOD: Script handles mechanics
def preprocess_tickets(tickets):
    # Filter
    open_tickets = [t for t in tickets if t['status'] == 'open']

    # Sort
    sorted_tickets = sorted(
        open_tickets,
        key=lambda t: (t['priority'], t['created_date']),
        reverse=True
    )

    # Group and limit
    by_component = {}
    for ticket in sorted_tickets:
        component = ticket['component']
        if component not in by_component:
            by_component[component] = []
        if len(by_component[component]) < 5:
            by_component[component].append(ticket['id'])

    return by_component

# Only pass result to LLM
top_tickets = preprocess_tickets(all_tickets)
prompt = f"""
Review these prioritized tickets: {top_tickets}
Recommend which component to focus on first.
"""
```

**Benefits**:
- 95%+ context reduction (50,000 → 500 tokens)
- Deterministic, testable logic
- Faster execution
- LLM focuses on judgment, not mechanics

---

### 2.3 Repeated Patterns

**Problem**: Same logic duplicated across multiple agents or orchestration steps.

```yaml
# ❌ BAD: Repeated pattern in multiple agents
agents:
  - name: plan-analyzer
    prompt: |
      Parse the drift report:
      1. Extract severity levels
      2. Count issues per file
      3. Identify critical patterns
      ...

  - name: drift-reviewer
    prompt: |
      Parse the drift report:
      1. Extract severity levels
      2. Count issues per file
      3. Identify critical patterns
      ...
```

**Solution**: Extract to shared script.

```python
# ✅ GOOD: Shared utility
# scripts/utils/parse_drift_report.py
def parse_drift_report(report_path):
    """Parse drift report into structured summary."""
    with open(report_path) as f:
        report = json.load(f)

    return {
        'severity_counts': count_by_severity(report),
        'issues_per_file': group_by_file(report),
        'critical_patterns': identify_critical_patterns(report),
        'summary': generate_summary(report)
    }
```

```yaml
# Agents use shared script
agents:
  - name: plan-analyzer
    prompt: |
      Run: python scripts/utils/parse_drift_report.py {report_path}
      Review the summary and assess impact on plan.

  - name: drift-reviewer
    prompt: |
      Run: python scripts/utils/parse_drift_report.py {report_path}
      Review the summary and recommend actions.
```

**Benefits**:
- Single source of truth for parsing logic
- Easier to test and maintain
- Consistent results across agents
- Logic changes don't require agent updates

---

### 2.4 Excessive Context Passing

**Problem**: Passing entire files or large data structures between agents when only small portions are needed.

```python
# ❌ BAD: Passing everything
step1_output = agent1.run({
    'drift_report': full_drift_report,  # 50KB
    'plan': full_plan,  # 20KB
    'tickets': all_tickets,  # 100KB
})

step2_output = agent2.run({
    'previous_context': step1_output,  # 170KB
    'drift_report': full_drift_report,  # 50KB again!
    ...
})
```

**Solution**: Pass summaries or specific fields.

```python
# ✅ GOOD: Pass only what's needed
step1_summary = {
    'high_severity_count': 3,
    'critical_files': ['auth.py', 'routes.py'],
    'key_issues': [
        'auth bypass in session validation',
        'missing input validation in API routes'
    ],
    'recommendation': 'Address auth issues before deployment'
}

step2_output = agent2.run({
    'previous_summary': step1_summary,  # <1KB
    'action_items': ['fix auth.py line 45', 'add validation routes.py']
})
```

**Benefits**:
- 99% reduction in context size
- Faster agent invocations
- Clearer data flow
- Forces explicit decisions about what's important

---

## 3. The Pattern Recognition Strategy

**When to use**: Processing many similar items (tickets, files, test results, drift items).

### The Strategy

```
1. LLM analyzes 3-5 samples → identifies pattern
2. LLM writes script implementing pattern
3. Script processes all items
4. LLM reviews only failures/edge cases
```

### Example: Processing 100 Drift Items

```python
# Step 1: Sample analysis
sample_items = drift_items[:5]
analysis_prompt = f"""
Analyze these drift report items and identify the pattern for categorization:

{json.dumps(sample_items, indent=2)}

Identify:
1. What fields determine severity?
2. What patterns indicate critical issues?
3. What can be categorized deterministically?
"""

pattern = llm.analyze(analysis_prompt)

# Step 2: LLM writes script
script_prompt = f"""
Based on this pattern: {pattern}

Write a Python script that categorizes drift items as:
- CRITICAL: Security issues, auth bypasses
- HIGH: Missing validation, error handling gaps
- MEDIUM: Style issues, minor improvements
- LOW: Documentation, comments

Return script code.
"""

script_code = llm.generate_script(script_prompt)

# Step 3: Script processes all items
with open('categorize_drift.py', 'w') as f:
    f.write(script_code)

categorized = subprocess.run(
    ['python', 'categorize_drift.py', '--input', 'drift_report.json'],
    capture_output=True
).stdout

# Step 4: LLM reviews edge cases
edge_cases = [item for item in categorized if item['confidence'] < 0.8]
review_prompt = f"""
Review these {len(edge_cases)} ambiguous categorizations:
{json.dumps(edge_cases, indent=2)}

Correct any misclassifications.
"""

final_result = llm.review(review_prompt)
```

### Benefits

- **90-95% context reduction**: 100 items × 1KB = 100KB → 5KB for samples + edge cases
- **Consistency**: Script applies same logic to all items
- **Speed**: Script execution is orders of magnitude faster
- **Testability**: Script can be unit tested
- **Reusability**: Script can be used in future orchestrations

### When Pattern Recognition Works Best

- ✅ Categorizing similar items (tickets, files, errors)
- ✅ Validating against consistent rules
- ✅ Extracting structured data from similar formats
- ✅ Applying transformations to datasets

### When to Avoid

- ❌ Items are highly heterogeneous
- ❌ Each item requires unique judgment
- ❌ Pattern is too complex for deterministic script
- ❌ Number of items is small (<10)

---

## 4. Script Extraction Patterns

### When to Extract to Script

Extract logic to scripts for:

#### 1. Deterministic Operations
```python
# Sorting, filtering, deduplication
def sort_tickets_by_priority(tickets):
    return sorted(tickets, key=lambda t: (t['priority'], t['created']))

def filter_open_tickets(tickets):
    return [t for t in tickets if t['status'] == 'open']
```

#### 2. File I/O Operations
```python
# Reading, writing, parsing files
def read_plan(plan_path):
    with open(plan_path) as f:
        return yaml.safe_load(f)

def write_summary(summary, output_path):
    with open(output_path, 'w') as f:
        json.dump(summary, f, indent=2)
```

#### 3. Data Aggregation
```python
# Counting, grouping, summarizing
def aggregate_drift_by_file(drift_items):
    by_file = {}
    for item in drift_items:
        file = item['file']
        if file not in by_file:
            by_file[file] = {'count': 0, 'severities': []}
        by_file[file]['count'] += 1
        by_file[file]['severities'].append(item['severity'])
    return by_file
```

#### 4. Pattern Matching (Regex-based)
```python
# Extracting structured data from text
import re

def extract_ticket_refs(text):
    pattern = r'\b[A-Z]+-\d+\b'
    return re.findall(pattern, text)

def parse_git_diff(diff_output):
    files_changed = re.findall(r'\+\+\+ b/(.*)', diff_output)
    return files_changed
```

#### 5. Validation Against Schemas
```python
# Schema validation, format checking
import jsonschema

def validate_plan(plan, schema_path):
    with open(schema_path) as f:
        schema = json.load(f)

    try:
        jsonschema.validate(plan, schema)
        return {'valid': True}
    except jsonschema.ValidationError as e:
        return {'valid': False, 'error': str(e)}
```

### When to Keep in LLM

Keep logic in LLM context for:

#### 1. Judgment Calls
```
"Is this code change high risk or low risk?"
"Should we prioritize security or performance?"
"Does this plan adequately address the requirements?"
```

#### 2. Ambiguous Categorization
```
"Is this error message indicating a critical issue or expected behavior?"
"Should this ticket be labeled 'bug' or 'feature request'?"
"Is this code comment helpful or just noise?"
```

#### 3. Natural Language Understanding
```
"What is the user trying to accomplish in this issue description?"
"Summarize the key points from this meeting transcript."
"What are the implications of this architecture decision?"
```

#### 4. Strategy Decisions
```
"What's the best approach to refactor this module?"
"How should we split this large task into subtasks?"
"What order should we tackle these issues?"
```

#### 5. Edge Case Handling
```
"This item doesn't fit any pattern we've seen. How should we handle it?"
"The validation failed in an unexpected way. What should we do?"
"This result looks suspicious. Should we investigate?"
```

---

## 5. Data Summarization Patterns

### 5.1 Before Passing Between Agents

**Rule**: Never pass full documents when summaries suffice.

```python
# ❌ BAD: Passing full drift report (500 lines)
agent_b_input = {
    'ticket': 'NES-XX',
    'drift_report': full_drift_report_text,  # 500 lines
    'plan': full_plan_text  # 200 lines
}

# ✅ GOOD: Passing summary
agent_b_input = {
    'ticket': 'NES-XX',
    'drift_summary': {
        'high_severity_count': 3,
        'critical_severity_count': 1,
        'key_issues': [
            'auth bypass in session validation',
            'missing input validation in API routes',
            'improper error handling in payment flow'
        ],
        'files_affected': ['auth.py', 'routes.py', 'payments.py'],
        'total_issues': 47
    },
    'plan_summary': {
        'task_count': 12,
        'estimated_hours': 16,
        'high_risk_tasks': ['refactor auth module', 'update API validators']
    }
}
```

### 5.2 Hierarchical Summarization

Use multiple levels of detail based on who needs what.

```python
# Level 1: Full Detail (stored in files, not passed around)
full_drift_report = {
    'items': [
        {
            'file': 'auth.py',
            'line': 45,
            'severity': 'CRITICAL',
            'issue': 'Session validation bypass...',
            'code_snippet': '...',
            'recommendation': '...',
            'references': [...]
        },
        # ... 46 more items
    ]
}
# Store to: .tasks/store/timestamp/drift_report_full.json

# Level 2: Key Points (passed to working agents)
drift_summary = {
    'critical_issues': [
        {
            'file': 'auth.py',
            'line': 45,
            'issue': 'Session validation bypass',
            'severity': 'CRITICAL'
        }
    ],
    'high_issues': [
        {'file': 'routes.py', 'issue': 'Missing input validation'},
        {'file': 'payments.py', 'issue': 'Improper error handling'}
    ],
    'medium_low_count': 44,
    'files_affected': ['auth.py', 'routes.py', 'payments.py', '...']
}
# Pass to agents working on specific issues

# Level 3: Counts Only (passed to orchestrator)
drift_overview = {
    'critical': 1,
    'high': 2,
    'medium': 20,
    'low': 24,
    'total': 47,
    'requires_immediate_attention': True
}
# Pass to orchestrator for high-level decisions
```

### 5.3 Summary Extraction Functions

Create reusable summary extractors:

```python
# scripts/utils/summarize.py

def summarize_drift_report(report_path, level='medium'):
    """
    Summarize drift report at specified detail level.

    Levels:
    - 'full': Return everything (use sparingly)
    - 'detailed': Include all critical/high, counts for medium/low
    - 'medium': Include critical only, counts for others
    - 'minimal': Counts only
    """
    with open(report_path) as f:
        report = json.load(f)

    items = report['items']
    by_severity = {
        'CRITICAL': [i for i in items if i['severity'] == 'CRITICAL'],
        'HIGH': [i for i in items if i['severity'] == 'HIGH'],
        'MEDIUM': [i for i in items if i['severity'] == 'MEDIUM'],
        'LOW': [i for i in items if i['severity'] == 'LOW']
    }

    if level == 'minimal':
        return {
            'critical': len(by_severity['CRITICAL']),
            'high': len(by_severity['HIGH']),
            'medium': len(by_severity['MEDIUM']),
            'low': len(by_severity['LOW']),
            'total': len(items)
        }

    elif level == 'medium':
        return {
            'critical_issues': [
                {'file': i['file'], 'line': i['line'], 'issue': i['issue']}
                for i in by_severity['CRITICAL']
            ],
            'high_count': len(by_severity['HIGH']),
            'medium_count': len(by_severity['MEDIUM']),
            'low_count': len(by_severity['LOW']),
            'files_affected': list(set(i['file'] for i in items))
        }

    # ... implement 'detailed' and 'full' levels
```

---

## 6. Orchestration Optimization Patterns

### 6.1 Batch Processing

**Don't call agent per item. Batch items and call once per batch.**

```python
# ❌ BAD: Agent per ticket
for ticket in tickets:  # 50 tickets
    result = agent.run({
        'ticket': ticket,
        'action': 'categorize'
    })
    results.append(result)
# 50 agent invocations, 50x context overhead

# ✅ GOOD: Batch processing
batch_size = 10
for i in range(0, len(tickets), batch_size):
    batch = tickets[i:i+batch_size]
    result = agent.run({
        'tickets': batch,
        'action': 'categorize_batch'
    })
    results.extend(result)
# 5 agent invocations, 10x reduction in overhead
```

### 6.2 Pre-computation

**Before orchestration: compute all static data. During orchestration: only dynamic decisions.**

```python
# ❌ BAD: Computing static data during orchestration
def orchestrate_plan_review(ticket_id):
    # Orchestration starts
    plan = load_plan(ticket_id)

    # Computing static schema (same for all tickets!)
    schema = load_schema('plan_schema.json')
    examples = load_examples('plan_examples/')

    # Agent invocation includes static data every time
    result = agent.run({
        'plan': plan,
        'schema': schema,  # Same every time
        'examples': examples  # Same every time
    })

# ✅ GOOD: Pre-compute static data once
# Pre-computation (run once at startup)
PLAN_SCHEMA = load_schema('plan_schema.json')
PLAN_EXAMPLES = load_examples('plan_examples/')

def orchestrate_plan_review(ticket_id):
    # Orchestration starts
    plan = load_plan(ticket_id)

    # Only dynamic data in agent invocation
    result = agent.run({
        'plan': plan,
        'schema_path': 'plan_schema.json',  # Agent loads if needed
        'examples_dir': 'plan_examples/'  # Agent loads if needed
    })
```

### 6.3 Checkpoint Files

**Write intermediate state to files. Resume from checkpoints, don't recompute.**

```python
# ❌ BAD: No checkpointing, must recompute everything on failure
def orchestrate_multi_step(ticket_id):
    # Step 1: Analyze (takes 30s)
    analysis = agent1.run({'ticket': ticket_id})

    # Step 2: Generate plan (takes 60s)
    plan = agent2.run({'analysis': analysis})

    # Step 3: Review plan (takes 45s) - FAILS
    review = agent3.run({'plan': plan})  # Error!

    # Now must re-run everything from scratch

# ✅ GOOD: Checkpoint intermediate results
def orchestrate_multi_step(ticket_id):
    checkpoint_dir = f'.tasks/store/{ticket_id}/checkpoints'
    os.makedirs(checkpoint_dir, exist_ok=True)

    # Step 1: Analyze (with checkpoint)
    analysis_checkpoint = f'{checkpoint_dir}/analysis.json'
    if os.path.exists(analysis_checkpoint):
        analysis = json.load(open(analysis_checkpoint))
    else:
        analysis = agent1.run({'ticket': ticket_id})
        with open(analysis_checkpoint, 'w') as f:
            json.dump(analysis, f)

    # Step 2: Generate plan (with checkpoint)
    plan_checkpoint = f'{checkpoint_dir}/plan.yaml'
    if os.path.exists(plan_checkpoint):
        plan = yaml.safe_load(open(plan_checkpoint))
    else:
        plan = agent2.run({'analysis': analysis})
        with open(plan_checkpoint, 'w') as f:
            yaml.dump(plan, f)

    # Step 3: Review plan (with checkpoint)
    review_checkpoint = f'{checkpoint_dir}/review.json'
    if os.path.exists(review_checkpoint):
        review = json.load(open(review_checkpoint))
    else:
        review = agent3.run({'plan': plan})
        with open(review_checkpoint, 'w') as f:
            json.dump(review, f)

    return review
    # If step 3 fails, steps 1-2 are preserved
```

---

## 7. Example: Optimized vs Unoptimized

### Scenario: Plan Quality Assessment Orchestration

Review a plan and its associated drift report to assess quality and identify risks.

### UNOPTIMIZED VERSION

```python
# orchestrations/plan_quality_assessment_unoptimized.py

def assess_plan_quality(ticket_id):
    """Unoptimized: Excessive context, redundant work, no batching."""

    # Load everything into memory
    plan_path = f'.tasks/store/{ticket_id}/plan.yaml'
    drift_path = f'.tasks/store/{ticket_id}/drift_report.json'

    with open(plan_path) as f:
        plan = yaml.safe_load(f)  # 200 lines

    with open(drift_path) as f:
        drift_report = json.load(f)  # 500 lines

    # Load schema and examples every time
    with open('.audit/schemas/plan_schema.json') as f:
        schema = json.load(f)  # 100 lines

    example_files = glob('.audit/examples/plans/*.yaml')
    examples = []
    for ex_file in example_files:
        with open(ex_file) as f:
            examples.append(yaml.safe_load(f))  # 5 files × 150 lines = 750 lines

    # Agent 1: Validate plan structure (passes full schema in context)
    validation_prompt = f"""
    Validate this plan against the schema:

    Schema:
    {json.dumps(schema, indent=2)}

    Examples:
    {yaml.dump(examples)}

    Plan to validate:
    {yaml.dump(plan)}
    """
    validation = llm.invoke(validation_prompt)
    # Context: ~1,050 lines

    # Agent 2: Analyze drift report (processes each item individually)
    drift_issues = []
    for item in drift_report['items']:  # 47 items
        issue_prompt = f"""
        Analyze this drift item and categorize severity:

        {json.dumps(item, indent=2)}

        Categorize as: CRITICAL, HIGH, MEDIUM, LOW
        """
        category = llm.invoke(issue_prompt)
        drift_issues.append({**item, 'category': category})
    # 47 LLM invocations, ~47 × 50 = 2,350 lines of context total

    # Agent 3: Compare plan to drift (passes everything again)
    comparison_prompt = f"""
    Compare this plan to the drift report and identify gaps:

    Plan:
    {yaml.dump(plan)}

    Drift report:
    {json.dumps(drift_report, indent=2)}

    Categorized issues:
    {json.dumps(drift_issues, indent=2)}

    Identify what the plan is missing.
    """
    gaps = llm.invoke(comparison_prompt)
    # Context: ~700 lines

    # Agent 4: Risk assessment (repeats all context)
    risk_prompt = f"""
    Assess risks for this plan:

    Plan:
    {yaml.dump(plan)}

    Drift report:
    {json.dumps(drift_report, indent=2)}

    Gaps identified:
    {gaps}

    Rate overall risk: LOW, MEDIUM, HIGH, CRITICAL
    """
    risk = llm.invoke(risk_prompt)
    # Context: ~700 lines

    # Agent 5: Generate recommendations (repeats all context again)
    rec_prompt = f"""
    Generate recommendations:

    Plan:
    {yaml.dump(plan)}

    Drift issues:
    {json.dumps(drift_issues, indent=2)}

    Gaps:
    {gaps}

    Risk level:
    {risk}

    Provide 3-5 specific recommendations.
    """
    recommendations = llm.invoke(rec_prompt)
    # Context: ~700 lines

    return {
        'validation': validation,
        'drift_issues': drift_issues,
        'gaps': gaps,
        'risk': risk,
        'recommendations': recommendations
    }

# METRICS:
# - LLM invocations: 51 (1 + 47 + 1 + 1 + 1)
# - Total context: ~5,500 lines
# - Execution time: ~5 minutes
# - Cost: High
```

### OPTIMIZED VERSION

```python
# orchestrations/plan_quality_assessment_optimized.py

def assess_plan_quality(ticket_id):
    """Optimized: Minimal context, scripts for mechanics, batching, checkpoints."""

    checkpoint_dir = f'.tasks/store/{ticket_id}/checkpoints'
    os.makedirs(checkpoint_dir, exist_ok=True)

    # Pre-computation: Run once
    plan_path = f'.tasks/store/{ticket_id}/plan.yaml'
    drift_path = f'.tasks/store/{ticket_id}/drift_report.json'

    # Step 1: Validate plan structure (script-based, deterministic)
    validation_checkpoint = f'{checkpoint_dir}/validation.json'
    if os.path.exists(validation_checkpoint):
        validation = json.load(open(validation_checkpoint))
    else:
        # Script validates against schema
        result = subprocess.run([
            'python', 'scripts/utils/validate_plan.py',
            '--plan', plan_path,
            '--schema', '.audit/schemas/plan_schema.json'
        ], capture_output=True, text=True)
        validation = json.loads(result.stdout)

        with open(validation_checkpoint, 'w') as f:
            json.dump(validation, f)
    # Context: 0 lines (script-based)

    # Step 2: Categorize drift items (pattern recognition)
    categorized_checkpoint = f'{checkpoint_dir}/drift_categorized.json'
    if os.path.exists(categorized_checkpoint):
        drift_summary = json.load(open(categorized_checkpoint))
    else:
        # Sub-step 2a: LLM analyzes 5 samples, writes categorization script
        drift_report = json.load(open(drift_path))
        samples = drift_report['items'][:5]

        pattern_prompt = f"""
        Analyze these 5 drift items and write a Python function that categorizes
        items as CRITICAL, HIGH, MEDIUM, or LOW based on patterns you identify:

        {json.dumps(samples, indent=2)}

        Return only the Python function code for: categorize_item(item) -> str
        """
        categorize_fn = llm.invoke(pattern_prompt)
        # Context: ~100 lines (5 samples only)

        # Sub-step 2b: Save and execute script on all items
        with open(f'{checkpoint_dir}/categorize_drift.py', 'w') as f:
            f.write(categorize_fn)

        result = subprocess.run([
            'python', f'{checkpoint_dir}/categorize_drift.py',
            '--input', drift_path,
            '--output', categorized_checkpoint
        ], capture_output=True)

        drift_summary = json.load(open(categorized_checkpoint))
    # Context: ~100 lines (one-time pattern recognition)

    # Step 3: Summarize data before comparison
    plan_summary = {
        'task_count': len(yaml.safe_load(open(plan_path))['tasks']),
        'components': list(set(
            t['component']
            for t in yaml.safe_load(open(plan_path))['tasks']
        )),
        'estimated_hours': sum(
            t.get('estimated_hours', 0)
            for t in yaml.safe_load(open(plan_path))['tasks']
        )
    }

    drift_summary_concise = {
        'critical_count': len([i for i in drift_summary['items'] if i['category'] == 'CRITICAL']),
        'high_count': len([i for i in drift_summary['items'] if i['category'] == 'HIGH']),
        'critical_files': list(set(
            i['file'] for i in drift_summary['items']
            if i['category'] == 'CRITICAL'
        )),
        'key_issues': [
            i['issue'] for i in drift_summary['items']
            if i['category'] in ['CRITICAL', 'HIGH']
        ][:5]  # Top 5 only
    }

    # Step 4: Single LLM invocation for analysis (batched judgment tasks)
    analysis_checkpoint = f'{checkpoint_dir}/analysis.json'
    if os.path.exists(analysis_checkpoint):
        analysis = json.load(open(analysis_checkpoint))
    else:
        analysis_prompt = f"""
        Assess this plan against drift report. Provide:
        1. Gaps: What critical/high drift issues are not addressed?
        2. Risk: Overall risk level (LOW/MEDIUM/HIGH/CRITICAL)
        3. Recommendations: 3-5 specific actions

        Plan summary:
        {json.dumps(plan_summary, indent=2)}

        Drift summary:
        {json.dumps(drift_summary_concise, indent=2)}

        Validation result:
        {json.dumps(validation, indent=2)}

        Return JSON: {{"gaps": [...], "risk": "...", "recommendations": [...]}}
        """
        analysis = llm.invoke(analysis_prompt)
        # Context: ~50 lines (summaries only)

        with open(analysis_checkpoint, 'w') as f:
            json.dump(analysis, f)

    return {
        'validation': validation,
        'drift_summary': drift_summary_concise,
        'analysis': analysis
    }

# METRICS:
# - LLM invocations: 2 (pattern recognition + final analysis)
# - Total context: ~150 lines
# - Execution time: ~30 seconds
# - Cost: Low
#
# IMPROVEMENTS:
# - 96% reduction in LLM invocations (51 → 2)
# - 97% reduction in context (5,500 → 150 lines)
# - 10x faster execution (5 min → 30 sec)
# - Checkpoints allow resumption on failure
# - Deterministic validation via script
# - Pattern recognition reduces repetitive analysis
```

---

## 8. Implementation Checklist

When designing an orchestration, use this checklist:

### Before You Start
- [ ] Identify all static data (schemas, examples, docs) - reference, don't embed
- [ ] Identify all deterministic operations - extract to scripts
- [ ] Identify all repeated patterns - create shared utilities
- [ ] Plan your data flow - what summaries are needed at each step?

### During Design
- [ ] Each agent prompt: Is there static content that could be referenced?
- [ ] Each agent task: Could a script do this deterministically?
- [ ] Each data pass: Am I passing full data or just what's needed?
- [ ] Each loop: Should this be batched or pattern-recognized?

### After First Draft
- [ ] Review total context usage - where are the hotspots?
- [ ] Identify opportunities for summarization
- [ ] Add checkpointing for expensive steps
- [ ] Consider caching for repeated operations

### Before Deployment
- [ ] Test with realistic data sizes
- [ ] Measure context usage per step
- [ ] Verify scripts are tested and reliable
- [ ] Document summarization levels and when to use each

---

## 9. Measuring Success

### Key Metrics

1. **Context Efficiency Ratio**
   ```
   CER = (Input Data Size) / (Context Used)

   Example:
   - Input: 50KB drift report
   - Context: 5KB summary passed to agent
   - CER = 50/5 = 10x

   Target: CER > 10x for most orchestrations
   ```

2. **LLM Invocation Count**
   ```
   Target: < 1 invocation per unique judgment required

   Red flags:
   - Invocations in loops over data
   - Same context passed multiple times
   - Invocations for deterministic operations
   ```

3. **Execution Time**
   ```
   Time = (Script Time) + (LLM Time) + (I/O Time)

   Optimize:
   - Script time: Use efficient algorithms
   - LLM time: Reduce invocations, context size
   - I/O time: Batch reads/writes, use checkpoints
   ```

4. **Checkpoint Coverage**
   ```
   Coverage = (Checkpointed Steps) / (Total Steps)

   Target: > 80% for multi-step orchestrations
   Benefits: Resume on failure, skip completed work
   ```

### Before/After Comparison Template

When optimizing an orchestration, measure:

```
BEFORE:
- LLM invocations: X
- Total context: Y lines/tokens
- Execution time: Z seconds
- Cost: $A

AFTER:
- LLM invocations: X' (reduction: %)
- Total context: Y' (reduction: %)
- Execution time: Z' (improvement: %)
- Cost: $A' (savings: %)

Optimizations applied:
1. ...
2. ...
3. ...
```

---

## 10. Common Pitfalls and Solutions

### Pitfall 1: "The LLM can handle it"

**Mindset**: LLMs are powerful, so let them do everything.

**Problem**: Wastes context on mechanical tasks, slower execution, higher cost.

**Solution**: Ask "Is this a judgment or a mechanic?" If mechanic → script.

---

### Pitfall 2: "It's only a few more lines"

**Mindset**: Adding schema/examples to prompt is just a few more lines.

**Problem**: "Few lines" × many invocations = huge context waste.

**Solution**: Track cumulative context usage across all invocations.

---

### Pitfall 3: "I'll optimize later"

**Mindset**: Get it working first, optimize later.

**Problem**: Optimization requires refactoring, which is harder after the fact.

**Solution**: Design with optimization patterns from the start. It's not slower.

---

### Pitfall 4: "Summarization loses information"

**Mindset**: Must pass full data to be safe.

**Problem**: Unnecessary context bloat, LLM overwhelm.

**Solution**: Use hierarchical summarization. Full data is in files, accessible if needed.

---

### Pitfall 5: "Scripts are more code to maintain"

**Mindset**: Scripts = more complexity.

**Problem**: True, but less complexity than debugging context-bloated LLM orchestrations.

**Solution**: Scripts are testable, reusable, and deterministic. Worth the investment.

---

## 11. Quick Reference

### When to Use Each Pattern

| Scenario | Pattern | Benefit |
|----------|---------|---------|
| Processing 10+ similar items | Pattern Recognition | 90-95% context reduction |
| Passing data between agents | Hierarchical Summarization | 95-99% context reduction |
| Sorting, filtering, grouping | Script Extraction | Deterministic, testable, fast |
| Schema validation | Script Extraction | Consistent, reliable |
| Multi-step orchestration | Checkpointing | Resume on failure |
| Repeated invocations | Batch Processing | Reduce overhead |
| Large static data | External References | Don't embed in prompts |
| Same logic in multiple agents | Shared Scripts | DRY, single source of truth |

### Decision Tree

```
Does this task require judgment or understanding?
├─ YES → Keep in LLM
│   └─ Is it repeated for many items?
│       ├─ YES → Pattern Recognition Strategy
│       └─ NO → Direct LLM invocation
│
└─ NO → Extract to script
    └─ Is it used in multiple places?
        ├─ YES → Create shared utility
        └─ NO → Inline script or local function
```

---

## Conclusion

Efficient context usage is not about doing less—it's about doing the right things in the right places:

- **LLMs**: For judgment, strategy, understanding
- **Scripts**: For mechanics, validation, transformation
- **Summarization**: For data passing between steps
- **Batching**: For repeated operations
- **Checkpointing**: For resilience and efficiency

By following these patterns, you can build orchestrations that are:
- **10-100x more efficient** in context usage
- **Faster** to execute
- **Cheaper** to run
- **More reliable** with checkpointing
- **Easier to maintain** with tested scripts

**Remember**: The goal is not to minimize LLM usage, but to maximize the value of every token of context you use.
