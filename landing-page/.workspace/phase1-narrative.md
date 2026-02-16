# Phase 1: Product Narrative + Objectives

## One-sentence positioning

Spec Manager is a quality control pipeline that runs multiple AI specialists
against your code through layered gates, so nothing reaches your branch
without passing inspection.

## Persona + job-to-be-done

**Primary persona: The vibe coder**

Uses AI tools (Claude Code, Cursor, Windsurf) to build software. Ships
fast. Does not have a traditional CS background. Knows enough to prompt
AI and read code but cannot reliably evaluate architecture, catch edge
cases, or enforce consistency across a growing codebase.

**Job-to-be-done:** "When I use AI to build my project, I want to know
the code is correct and complete without having to become a software
engineer to verify it."

**Emotional state:** Excited about AI coding speed. Frustrated by
mysterious breakage. Suspicious the AI is cutting corners. Afraid of the
codebase becoming unmaintainable. Does not know the name for what is going
wrong (spec drift, reward hacking, governance gaps).

## Primary CTA + secondary CTA

- **Primary:** "Join the Waitlist" (email capture, low commitment)
- **Secondary:** "See how it works" (scroll to mechanism section)

## Top 5 objections (in persona's voice)

1. "Is this just another Cursor/Copilot?" (category confusion)
2. "I don't know how to code. Can I still use this?" (capability anxiety)
3. "My code is private. Where does it go?" (privacy/trust)
4. "I already use Cursor. Do I have to switch?" (switching cost)
5. "When can I actually try it?" (vaporware suspicion)

## Proof inventory (what we can actually show)

**Hard proof:**
- 723 tests passing (real, in codebase)
- 52/52 requirements captured in eval testing (real metric)
- Built by Nestharus (founder credibility, 25 years building tools)
- Works with Claude Code, Cursor, Windsurf (integration breadth)

**Soft proof:**
- Active development (prototype in progress)
- Open about being pre-launch (honesty builds trust)
- Three pricing tiers including free (low risk)

**What we do NOT have (and must not fake):**
- No user testimonials
- No case studies
- No logo wall
- No usage metrics
- No third-party reviews

This means social proof must lean on builder credibility and technical
rigor, not adoption numbers. The honesty itself is a trust signal for
this audience.

---

# Phase 2: Asset Plan

## What we can show (constrained by: no UI exists yet)

### Available assets

| Asset | Source | Purpose |
|-------|--------|---------|
| Pipeline diagram | Custom SVG/CSS | Hero visual, mechanism |
| Quality gate flow | CSS animation | How-it-works |
| Pricing tiers | Static cards | Offer section |
| Test count badge | Real metric | Social proof |
| Eval accuracy | Real metric (52/52) | Trust building |
| Code snippets | Spec comment examples | "Code IS the spec" demo |

### Not available (do not attempt)

| Missing | Why it matters |
|---------|---------------|
| Product UI screenshots | No UI exists |
| Video demo | No product to demo |
| User testimonials | Pre-launch |
| Logo wall | No customers |

### Visual asset strategy

Since we have no product UI, the visual story must be carried by:

1. **Abstract pipeline visualizations** (code flowing through gates)
2. **Conceptual diagrams** (multi-AI review process)
3. **Typography and layout** (editorial quality carries perceived value)
4. **Ambient atmosphere** (glow, gradient, grain establish tone)

The page must feel like a product preview through its design quality,
not through product screenshots.

---

# Phase 3: Information Architecture Storyboard

## Scene 1: Hook + Promise (Hero)

**User question answered:** "What is this? Is it for me?"

**Content:**
- Headline that names the problem + implies the solution
- Subhead that explains the mechanism in one sentence
- Two CTAs: primary (waitlist) + secondary (learn more)
- Pipeline visual showing the three quality layers
- Scroll indicator (prevent "illusion of completeness")

**Proof element in hero:** None forced. The visual quality IS the proof
at this stage. Pipeline visual demonstrates the concept.

## Scene 2: Problem (Recognition)

**User question answered:** "Wait, I've felt this exact thing."

**Content:**
- 4 problem cards, each naming a specific pain
- Each card: icon + title + 2-3 sentences of specific, felt description
- Cards appear on scroll (staggered reveal)

**Narrative job:** Start with pain they can name ("things break"), then
name the pain they cannot articulate ("nobody checks the AI's work").
Move from obvious to hidden.

## Scene 3: Solution (Mechanism)

**User question answered:** "How does this actually work?"

**Content:**
- The three-layer pipeline: Build, Organize, Polish
- Each layer: what happens, who checks, what fails get sent back
- Visual: directional flow with gates

**Narrative job:** Show the mechanism is structured, not magic. Multiple
AIs with different jobs, checking each other. Failures go backward, not
forward.

## Scene 4: Simplification (How it works in 3 steps)

**User question answered:** "OK but what do I actually do?"

**Content:**
- Step 1: Write a spec in plain language
- Step 2: AI builds with guardrails (multiple specialists, quality gates)
- Step 3: Ship verified code

**Narrative job:** Collapse the complexity into user-facing simplicity.
The user's job is tiny. The system does the rest.

## Scene 5: Proof + Features

**User question answered:** "Is this real? What specifically do I get?"

**Content:**
- Social proof strip (test count, builder, integrations)
- Feature bento grid (6 capabilities, each as a card)
- Each card: benefit headline + specific mechanism + no fluff

**Narrative job:** Transition from "how" to "what." The bento grid
compresses breadth into scannable chunks.

## Scene 6: Differentiation

**User question answered:** "How is this different from Cursor/Copilot?"

**Content:**
- Simple framing: other tools help write code faster, this ensures
  correctness
- NOT a feature comparison table (too technical for persona)
- Body paragraph grounding the distinction

**Narrative job:** Position against the category the user knows, without
attacking it. "Adds quality control on top."

## Scene 7: Offer (Pricing)

**User question answered:** "What does it cost? Can I try it?"

**Content:**
- Three tiers: Free (local), Hybrid ($15/mo), Cloud (TBD)
- Free tier prominent (low friction for waitlist audience)
- CTA button below pricing

**Narrative job:** Remove price anxiety. Free tier exists. No credit card.

## Scene 8: Objections (FAQ)

**User question answered:** "What about [concern]?"

**Content:**
- 5 questions addressing the top 5 objections from Phase 1
- Each answer: direct, specific, honest

**Narrative job:** Reduce remaining friction. The FAQ is a conversion
device, not a support document.

## Scene 9: Final CTA

**User question answered:** "OK, what do I do now?"

**Content:**
- Headline that echoes the hero promise
- Email form
- Friction reducer text

**Narrative job:** The CTA should feel like the obvious next step, not
a hard sell.
