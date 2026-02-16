# Copy Improvements: Specific Fixes

All copy must pass the WRITING_SKILL_MASTER.md hard bans:
- No em dashes
- No sentences starting with But, And, So, Or, Still, Yet, However, Therefore
- No triads (X, Y, Z)
- No three consecutive sentences with same opening word or grammatical frame
- No hedging (might, could, perhaps)
- No posturing (Everyone gets this wrong, The real truth is)
- No cliches
- No performative summary sentences

## Problem: "AI asks, not guesses"

This is vague tagline-speak. What does "asks" mean? The reader doesn't
know what behavior this describes.

**Current (bad):**
"AI asks, not guesses"
"When something's ambiguous, the system stops and asks you. You make
the decision. The AI executes it."

**Problem:** Three consecutive sentences with similar structure
(statement, statement, statement). "AI asks, not guesses" is a contrast
pair used as a title, which reads as a slogan. The body text is three
short declarative sentences in a row — same grammatical frame.

**Improved title:** "Ambiguity stops the line"

**Improved body:** "When the AI hits something underspecified, the
pipeline halts. You get a question with context about what is unclear
and why it matters. Your answer becomes a constraint the AI follows
for the rest of the build."

**Why this is better:**
- The title describes a concrete behavior (pipeline halts), not a vague virtue
- "Stops the line" uses the assembly line metaphor consistently
- The body describes a sequence (halt → question → answer → constraint)
  instead of restating the same idea three ways
- "Constraint" is a specific mechanism, not a vague "decision"

## Problem: Hero subhead

**Current:**
"Multiple AI specialists write and review your code through quality gates
before it ships. No engineering degree required."

**Issues:** "write and review" is a mini-list. "No engineering degree
required" is a separate claim tacked on.

**Improved:**
"Multiple AI specialists review your code through quality gates before
it ships. You describe what you want in plain language."

**Why:** The second sentence does the job of "no engineering degree" by
showing the user's actual interaction. More concrete.

## Problem: Differentiator body

**Current:**
"Other tools optimize for speed. Spec Manager optimizes for correctness.
Code that passes through Spec Manager has been reviewed by multiple AI
specialists before you see it. Code from other tools has been reviewed
by nobody."

**Issues:** Four sentences, two pairs of parallel contrast. The last two
sentences have identical grammatical frames ("Code that/from X has been
reviewed by Y"). This is a contrast pair used as a metronome.

**Improved:**
"Other tools optimize for speed. Spec Manager optimizes for correctness.
Every function that reaches your branch has passed through multiple AI
reviewers, each checking different things. The code you get from other
tools went straight from one AI to your project with no inspection."

**Why:** Breaks the parallel structure. "Every function" is more specific
than "Code that passes through." The second comparison uses a different
sentence shape.

## Problem: Solution card bodies

**Card 1 (Build) current:**
"AI writes code from your spec. The system tracks every function against
the requirements. When something is unclear, it asks you instead of guessing."

**Issues:** Three sentences, all declarative, similar length. Third
sentence echoes "AI asks, not guesses" from bento grid — repetitive
across the page.

**Card 1 improved:**
"AI writes code from your spec while a coverage ledger tracks every
function against the requirements. Nothing gets marked complete until
the ledger confirms full coverage."

**Card 2 (Organize) current:**
"Working code gets structured properly. Architecture reviewers check
the design. Logic bugs get sent back for proper fixes instead of patches."

**Issues:** Three short declarative sentences, same frame.

**Card 2 improved:**
"Working code gets structured into a clean architecture. Five reviewers
check the design independently. When they find logic bugs, the code goes
back to Build for a real fix instead of a patch at the wrong layer."

**Card 3 (Polish) current:**
"Code quality reviewers check for clarity and correctness.
Only code passing all gates reaches your main branch."

**Issues:** Fine but thin. Could be more specific.

**Card 3 improved:**
"Code quality reviewers check for clarity and correctness. Only code
that passes all gates reaches your main branch. You can trace every
function back to the spec requirement that produced it."

## Problem: Bento card "Your process, your rules"

**Current:**
"Build custom workflows with the AI models you choose. Your team can
share and reuse them."

**Issues:** Two short sentences, vague. "Build custom workflows" could
mean anything. "Share and reuse" is filler.

**Improved:**
"Define how work moves through the pipeline with the AI models you
choose. Workflows are portable. Your team runs the same process on
every project."

**Why:** "Define how work moves through the pipeline" is specific to
this product. "Portable" is concrete. "Same process on every project"
describes the actual benefit.

## Problem: Bento card "Walk away and come back"

**Current:**
"State persists across sessions. Crash-proof. Pick up exactly where
you left off."

**Issues:** Three staccato fragments in a row. "Crash-proof" is a bare
adjective, not a sentence.

**Improved:**
"State persists across sessions. If your machine crashes mid-build,
the pipeline resumes from the last completed gate. No work lost."

**Why:** "If your machine crashes mid-build" is a concrete scenario.
"Resumes from the last completed gate" describes the actual mechanism.

## Problem: FAQ answer 1 (Cursor/Copilot comparison)

**Current:**
"No. Those are AI coding assistants: one AI writes code, then you
review it. Spec Manager is a quality pipeline. Multiple AIs write
and review code through gates before it reaches you."

**Issues:** "write and review" is a mini-list that appears multiple
times across the page. Four sentences, first three are very short.

**Improved:**
"No. Those give you one AI that writes code for you to review. Spec
Manager runs your code through a pipeline of specialized AI reviewers
before it reaches your branch. The difference is who does the quality
control: you alone, or a system of gates."

## Problem: Final CTA subtext

**Current:**
"Your AI writes the code. Now something checks if it's right. Join
the waitlist."

**Issues:** "Join the waitlist" as a sentence is redundant with the
form button right below it.

**Improved:**
"Your AI writes the code. Spec Manager checks if it's right."

**Why:** Shorter. No redundant CTA instruction. The form IS the action.
