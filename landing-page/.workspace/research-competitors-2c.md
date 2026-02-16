# Competitor Research: Agent Flywheel & Gas Town (Beads)

Research date: 2026-02-14
Sources scraped: agent-flywheel.com (main, /flywheel, /learn/welcome), gastown.dev (main, /docs/overview, /docs/why-these-features, /docs/concepts/polecat-lifecycle, /docs/concepts/convoy)

---

## 1. Agent Flywheel

**URL**: https://agent-flywheel.com/
**Creator**: Jeffrey Emanuel (individual, PE/hedge fund consulting background)
**License**: Free and open-source
**GitHub**: https://github.com/Dicklesworthstone/agentic_coding_flywheel_setup

### What Problem It Solves

Agent Flywheel solves the **setup and tooling fragmentation** problem for agentic coding. The core pain points:
- Getting started with AI coding agents is intimidating for non-engineers
- Running multiple AI agents (Claude Code, Codex CLI, Gemini CLI) requires significant server configuration
- No unified tooling exists for coordinating, searching, and managing multi-agent workflows
- Agents working in parallel need coordination (messaging, file reservations, safety guardrails)

The pitch: "Transform a fresh cloud server into a fully-configured agentic coding environment in ~30 minutes."

### How It Works (Architecture/Workflow)

**Layer 1 -- Infrastructure Setup (The Installer)**
A single curl command installs onto an Ubuntu VPS:
- Three AI agents: Claude Code, Codex CLI, Gemini CLI
- 30+ developer tools: zsh, oh-my-zsh, powerlevel10k, lsd, bat, ripgrep, fzf, zoxide
- Language runtimes: Bun, Python (uv), Rust, Go
- Idempotent installation with SHA256 verification
- 13-step wizard guides users from laptop to working VPS

**Layer 2 -- The Flywheel (29 Interconnected Tools)**
The real product is an ecosystem of 29 open-source tools across Go, Rust, TypeScript, Python, and Bash. Core tools (8):

| Tool | Purpose | Stars |
|------|---------|-------|
| NTM (Named Tmux Manager) | Multi-agent tmux session orchestration | 69 |
| Mail (MCP Agent Mail) | Inter-agent messaging, file reservations | 1.4K |
| UBS (Ultimate Bug Scanner) | 1000+ pattern bug detection across 8 langs | 132 |
| BV (Beads Viewer) | DAG-based task prioritization (PageRank) | 891 |
| CASS (Agent Session Search) | Unified search across 11 agent formats | 307 |
| CM (CASS Memory) | Cross-agent procedural memory | 152 |
| SLB (Simultaneous Launch Button) | Two-person rule for dangerous commands | 49 |
| DCG (Destructive Command Guard) | SIMD-accelerated command blocking | 89 |

Plus 21 supporting tools for issue tracking, account management, repo sync, research orchestration, etc.

**Layer 3 -- The Workflow**
The flywheel loop:
1. NTM spawns 6+ agents across tmux sessions
2. Agents discover tasks via BV (graph-based prioritization)
3. Agents coordinate via Mail (messaging + file reservations)
4. CASS indexes all sessions; CM stores procedural memory
5. UBS scans for bugs; SLB/DCG provide safety guardrails
6. Agents review each other's work
7. 3+ hours of autonomous progress while human is away

**The "Flywheel Effect"**: The thesis is that using 3 tools together is 10x better than using 1. Each tool amplifies the others through JSON, MCP, and Git composition.

### Target Audience

**Primary**: Individual developers willing to invest $440-656/month
- People who find Lovable.dev too limiting
- People who want AI writing "real, production code"
- No coding experience required -- just "patience and motivation"
- Heavily targets non-technical users who have heard about AI coding

**Secondary**: Power users running 6+ agents across 8+ projects simultaneously

**Explicitly NOT for**:
- People wanting a free solution
- People wanting only occasional AI help
- Mobile-first developers
- Enterprise compliance requirements

### Key Differentiators

1. **Completeness of setup**: Goes from "I have a laptop" to "AI agents are coding for me" -- extremely low barrier to entry
2. **Ecosystem breadth**: 29 tools that interoperate, not a single monolith
3. **VPS-first philosophy**: Agents run on dedicated compute 24/7, work while you sleep
4. **Safety engineering**: Two-person rule (SLB), command guard (DCG), defense-in-depth approach
5. **Cross-agent memory**: CASS + CM create persistent, shared memory across agent types
6. **Interactive learning**: 33-lesson onboarding tutorial from Linux basics to agent orchestration
7. **Radical transparency**: Explicit about costs, who it's for, who it's not for

### Messaging Tone and Copy Strategy

**Tone**: Enthusiastic but honest. Jeffrey Emanuel as the relatable individual, not a corporate entity. The copy is warm, personal, slightly breathless about possibilities but with genuine "Is this for you?" honesty sections.

**Hero copy**: "AI Agents Coding For You" -- direct, active voice
**Subhead**: "Zero to agentic coding in 30 minutes" -- concrete time promise
**Tagline energy**: "Unheard-of Velocity in Complex Software"

**Copy strategies observed**:
- **Social proof via numbers**: "30+ Tools, 3 AI Agents, ~30m Setup Time, 2K+ GitHub Stars"
- **Concrete specifics over vague claims**: "$40-56/month" not "affordable"; "3+ hours autonomous" not "works autonomously"
- **Explicit cost comparison**: "A junior developer costs $5,000+/month. For under $700, you get 10+ AI agents working 24/7"
- **Radical transparency sections**: "Is This For You?" with honest "not for you if" lists
- **Battle-tested prompts**: Actual copy-paste prompts users can use immediately
- **Workflow-first storytelling**: "Daily Parallel Progress", "Agents Reviewing Agents", "5,500 Lines to 347 Beads"

**Visual/design approach**: Dark theme, terminal aesthetic, command-line UI elements, step-by-step wizards. Statistics presented as prominent counters. The site itself feels like a well-designed dev tool landing page.

### Strengths

1. **Extremely low barrier to entry** -- designed for people with zero coding experience
2. **Cost transparency** -- unusual and effective for trust-building
3. **Real workflows, not hypotheticals** -- the prompts section shows actual daily usage patterns
4. **Ecosystem network effects** -- 29 tools create lock-in through interconnection
5. **Personal brand** -- Jeffrey Emanuel as an individual creator builds authenticity
6. **Open source** -- removes adoption friction entirely; the revenue model is the AI subscriptions, not the tools
7. **Learning content** -- 33 lessons systematically build competence

### Weaknesses

1. **Individual developer only** -- explicitly disclaims enterprise use. No team features, no org-level coordination
2. **High ongoing cost** -- $440-656/month is steep for individuals; the "cheaper than a junior dev" comparison only works if you're actually replacing a junior dev
3. **VPS complexity** -- despite the wizard, managing a VPS is a new skill for non-technical users
4. **Tool sprawl** -- 29 tools creates cognitive overhead; hard to know what to use when
5. **Single maintainer risk** -- everything depends on Jeffrey Emanuel's continued motivation
6. **No quality/correctness guarantees** -- the flywheel produces output but has no formal verification of whether that output is correct beyond bug scanning patterns
7. **"Vibe coding" philosophy** -- "Passwordless sudo with dangerous flags enabled" is explicitly for throwaway environments, limiting production use
8. **No structured work decomposition** -- BV tracks task graphs but there's no formal methodology for how work gets broken down or verified
9. **Agent coordination is advisory** -- Mail provides messaging and file reservations, but nothing prevents conflicts; coordination is best-effort

---

## 2. Gas Town / Beads

**URL**: https://gastown.dev/
**Description**: "A multi-agent orchestration system for coding agents with persistent work tracking"
**Docs**: Docusaurus-based, technical, comprehensive
**Maturity**: Appears earlier stage; docs-heavy, less marketing polish

### What Problem It Solves

Gas Town addresses **accountability, quality, and coordination** at scale for AI agent workforces. The core pain points:
- **Accountability**: "Which agent introduced this bug?" -- git blame shows generic "AI Assistant"
- **Quality**: "Which agents are reliable? Which need tuning?" -- no track record system exists
- **Efficiency**: "How do you route work to the right agent?" -- manual assignment doesn't scale
- **Scale**: "How do you coordinate agents across repos and teams?" -- traditional tools don't track agent performance

The key insight: "Traditional tools don't help. CI/CD tracks builds, not capability. Git tracks commits, not agent performance."

### How It Works (Architecture/Workflow)

**Core Abstraction: Work as Structured Data ("Work Ledger")**
Every action is recorded, every agent has a track record, every piece of work has provenance.

**Role Taxonomy**:

*Infrastructure roles (persistent, system-level)*:
| Role | Description |
|------|-------------|
| Mayor | Global coordinator (singleton) |
| Deacon | Background supervisor daemon (watchdog chain) |
| Witness | Per-rig polecat lifecycle manager |
| Refinery | Per-rig merge queue processor |

*Worker roles (do actual project work)*:
| Role | Description |
|------|-------------|
| Polecat | Ephemeral worker with persistent identity -- Witness-managed |
| Crew | Persistent worker with own clone -- human-managed |
| Dog | Deacon helper for narrow infrastructure tasks |

**Key Concepts**:

1. **Rigs**: Project containers (like repos) with their own config, workers, and beads (issue tracking)
2. **Beads**: Git-backed structured issue tracking that integrates with the orchestration system
3. **Convoys**: Batched work tracking across rigs -- the "what's in flight" dashboard
4. **Polecats**: The core innovation -- ephemeral worker sandboxes with persistent identity:
   - Three-layer architecture: Identity (permanent CV/work history), Sandbox (ephemeral git worktree), Session (ephemeral Claude instance)
   - Self-cleaning: when done, the polecat pushes its branch, submits to merge queue, and self-destructs
   - No idle state: polecats exist only while working; stalled/zombie states are explicitly failure modes
5. **Refinery**: Merge queue processor that handles rebasing and conflict resolution (spawns fresh polecats for re-implementation)
6. **Witness**: Monitors polecats, nudges stalled ones, cleans up zombies, respawns crashed sessions

**The Propulsion Principle**: "If you find something on your hook, YOU RUN IT." All agents execute immediately without waiting for confirmation. Gas Town is a "steam engine -- agents are pistons."

**Directory Structure** (physically realized on filesystem):
```
~/gt/                           Town root
  .beads/                       Town-level issue tracking
  mayor/                        Global coordinator
  deacon/dogs/                  Infrastructure helpers
  <rig>/                        Per-project container
    .repo.git/                  Bare repo (shared by worktrees)
    refinery/                   Merge queue processor
    witness/                    Monitor (no clone)
    crew/                       Human-managed persistent workspaces
    polecats/                   Ephemeral worker sandboxes
```

### Target Audience

**Primary**: Teams/organizations running multiple AI coding agents at scale
- Engineering teams deploying 10-50+ agents across multiple repos
- Organizations needing accountability, attribution, and audit trails
- Teams doing model evaluation (A/B testing Claude vs GPT on real tasks)

**Secondary**: Enterprise organizations needing:
- SOX/GDPR compliance for AI agent work
- Cross-org coordination (contractors, partners) via federation
- Performance management of AI agent workforce

### Key Differentiators

1. **Attribution as first-class primitive**: Every action has a named actor; git commits carry agent identity, not generic "AI Assistant"
2. **Agent CVs / Work History**: Persistent track records across ephemeral sessions. Enables capability-based routing ("which agent handles Go best?")
3. **Three-layer polecat architecture**: Clean separation of persistent identity, ephemeral sandbox, ephemeral session. Sessions cycle constantly (normal operation, not failure). Work survives session restarts.
4. **Merge queue (Refinery)**: Structured merge pipeline with conflict detection. On conflict, spawns a fresh polecat to re-implement -- never sends work back to original.
5. **Convoys for batch tracking**: Cross-rig visibility into "what's in flight" with auto-notification on landing
6. **Federation**: First-class multi-repo, multi-org support from day one
7. **Model evaluation**: Because every task has completion time, quality signals, and revision count, you can objectively compare models on real work
8. **Enterprise value proposition framed explicitly**: Attribution for compliance, validation for quality gates, activity feed for operational awareness

### Messaging Tone and Copy Strategy

**Tone**: Technical, precise, opinionated. Documentation-first -- reads like well-written internal engineering docs, not marketing copy. Uses industrial/mechanical metaphors throughout (steam engine, pistons, refinery, polecats, convoys).

**Marketing page (gastown.dev/)** is sparse -- three feature cards:
- "Persistent work state" -- hooks store agent output in git worktrees
- "Mayor-led coordination" -- Mayor creates convoys, assigns beads
- "Beads-based tracking" -- git-backed issue tracking

**Docs positioning**: "Why These Features?" page systematically walks through enterprise AI challenges and maps them to Gas Town features. Each section follows a pattern:
1. "The problem:" (specific pain point)
2. "The solution:" (Gas Town's approach with code examples)
3. "Why it matters:" (bullet points of value)

**Copy strategies observed**:
- **Problem-first framing**: Every feature is motivated by a specific question the user can't answer today
- **Anti-pattern documentation**: Explicitly calls out what NOT to do and why, building credibility
- **Code-heavy**: Almost every concept includes bash examples and ASCII diagrams
- **Opinionated vocabulary**: "Heresies" for wrong mental models, "Propulsion Principle" for execution philosophy
- **Enterprise positioning through developer framing**: "Gas Town is a developer tool -- like an IDE, but for AI orchestration. However, the architecture provides enterprise-grade foundations."

**Design**: Docusaurus docs site. Minimal visual design. Social card imagery exists but the marketing page is bare-bones. The investment is entirely in documentation quality.

### Strengths

1. **Deep architecture**: The three-layer polecat model is genuinely novel and well-thought-out. Clean separation of concerns between identity, sandbox, and session.
2. **Attribution solves a real blind spot**: No other tool properly attributes AI agent work at the git level
3. **Enterprise readiness**: Federation, validation gates, audit trails, compliance -- these are real enterprise requirements that competitors ignore
4. **Merge queue intelligence**: The Refinery's approach (fresh polecat for conflicts rather than sending work back) is a smart design choice
5. **Model evaluation built-in**: The work ledger naturally enables A/B testing of AI models on real tasks
6. **Anti-fragile worker model**: Self-cleaning polecats with no idle state means the system degrades gracefully. Failure modes are explicitly enumerated and handled.
7. **Cross-rig coordination**: Convoys + worktrees + dispatch give multiple patterns for cross-project work
8. **Opinionated documentation**: The anti-patterns and "common mistakes" sections show deep experience with the problem space

### Weaknesses

1. **Marketing is nearly absent**: The main page has three feature cards and that's it. No hero copy, no pricing, no "getting started" flow. All the value is buried in docs.
2. **High cognitive overhead**: The vocabulary is dense (Polecats, Beads, Convoys, Rigs, Witness, Deacon, Refinery, Mayor, Dogs, Crews, Molecules, Hooks). New users face a steep learning curve.
3. **No clear adoption path**: Unlike Agent Flywheel's wizard, there's no obvious "start here" for a new user
4. **Maturity concerns**: Several features mention "not yet implemented" (e.g., `gt convoy add`). The system appears to be in active development.
5. **Unclear pricing/availability**: Is this open-source? SaaS? Self-hosted? The docs don't say.
6. **No ecosystem breadth**: Gas Town is deep but narrow -- it orchestrates agents but doesn't provide the 29-tool breadth of Agent Flywheel
7. **Assumes existing agent infrastructure**: You need to already have AI coding agents running; Gas Town adds orchestration on top
8. **Single-platform risk**: Tight coupling to Claude Code (tmux sessions, context compaction handling) though the architecture is theoretically agent-agnostic

---

## Comparative Analysis

### Positioning Matrix

| Dimension | Agent Flywheel | Gas Town |
|-----------|---------------|----------|
| **Primary value prop** | Setup + tooling ecosystem | Orchestration + accountability |
| **Entry point** | "I want AI agents coding for me" | "I have AI agents, I need to manage them" |
| **Target user** | Individual developer, possibly non-technical | Engineering team/org at scale |
| **Complexity** | Low barrier, high breadth | High barrier, high depth |
| **Architecture** | Loosely coupled Unix tools | Tightly integrated role-based system |
| **Work tracking** | BV (task graph) + BR (issue tracking) | Beads (git-backed) + Convoys (batch tracking) |
| **Agent coordination** | Mail (advisory messaging) | Mayor + Witness + Refinery (structured orchestration) |
| **Safety** | SLB + DCG (command-level guardrails) | Validation gates + Refinery merge queue |
| **Memory/learning** | CASS + CM (session search + procedural memory) | Agent CVs + work history (capability routing) |
| **Marketing maturity** | Polished landing page, wizard, learning hub | Bare docs site, no marketing copy |
| **Revenue model** | Free tools; user pays AI providers | Unclear |
| **Open source** | Yes, explicitly | Unclear |

### Key Insight: Different Layers of the Stack

These two products operate at fundamentally different layers:

- **Agent Flywheel** = Infrastructure + Tooling layer. "Here are the tools. Here's how to set them up. Here are prompts. Go." It's horizontal -- many tools, loosely coupled, Unix philosophy.

- **Gas Town** = Orchestration + Governance layer. "Here's how to manage an AI agent workforce with accountability, quality control, and cross-project coordination." It's vertical -- deep architecture, tight integration, enterprise governance.

A team could theoretically use both: Flywheel's tools (NTM, CASS, UBS, DCG) for the individual agent experience, and Gas Town's orchestration (Mayor, Witness, Refinery, Convoys) for the fleet management layer.

### Messaging Lessons

**From Agent Flywheel**:
- Radical cost transparency builds trust
- "Is this for you? / Is this NOT for you?" honesty is disarming and effective
- Concrete numbers beat vague claims (30 minutes, $440/month, 3+ hours autonomous)
- Battle-tested prompts as content serve dual duty: demonstrate the workflow AND give users immediate value
- The flywheel metaphor (tools amplifying each other) is compelling
- Personal creator story adds authenticity

**From Gas Town**:
- Problem-first feature framing forces relevance
- Anti-pattern documentation builds credibility and shows depth of experience
- Industrial metaphors (steam engine, refinery, convoys) create a coherent world
- The enterprise value table (developer benefit vs enterprise benefit) is an effective dual-audience technique
- "Work as structured data" is a powerful reframing of the problem space
- Attribution is an underserved need that resonates immediately

### What Neither Does Well

1. **Verification of output quality**: Neither tool has a systematic way to verify that AI-generated code is actually correct beyond pattern-matching bug scanners (Flywheel's UBS) or generic quality gates (Gas Town's validation). No formal proof, property testing, or specification conformance.

2. **Work decomposition methodology**: Both track tasks but neither provides a principled methodology for how complex work gets broken down into agent-sized units. Agent Flywheel uses prompts ("create comprehensive beads"); Gas Town uses manual issue creation.

3. **Layer-aware code quality**: Neither distinguishes between different kinds of work (architecture vs implementation vs refactoring) or gates promotion through quality layers.

4. **Specification-driven development**: Neither starts from a specification and systematically decomposes it into verifiable implementation steps with formal promotion criteria.

5. **Cost optimization at the workflow level**: Agent Flywheel tracks costs (CAUT), Gas Town enables model comparison, but neither optimizes the workflow itself to minimize wasted inference tokens or failed attempts.
