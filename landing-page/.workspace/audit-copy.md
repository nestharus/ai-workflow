# Landing Page Copy Audit

Audited against: `scripts/article_writer/WRITING_SKILL_MASTER.md`

The writing guide targets articles and essays, not landing pages. Landing pages allow more closure, more structure, and more direct persuasion. This audit applies the universal principles (banned patterns, cadence, concrete-before-abstract, every-sentence-has-a-job) while relaxing article-specific rubrics (hidden skeleton, lens shift, anti-closure bias).

---

## 1. Hero Headline + Subhead

**Headline:**
> Your AI writes the code.
> Who checks if it's right?

**Subhead:**
> Multiple AI specialists write, review, and organize your code through quality gates -- so nothing ships broken. No engineering degree required.

### Violations

**Em dash.** The subhead uses `&mdash;`. Hard ban: "No em dash characters."

**Triad in prose.** "write, review, and organize" is a textbook X, Y, and Z triad. This pattern appears five times across the page (see recurring issues below).

**Subhead tries to do too much.** It packs the product mechanism, the benefit, and the audience qualifier into one sentence. The result is a comma-heavy sentence that reads like a list (soft tell).

### Suggested rewrite

> Multiple AI specialists write and review your code through quality gates before it ships. No engineering degree required.

Drop "organize" (it is the vaguest of the three verbs and gets its own section later). Replace the em dash with a sentence break.

### What works

The headline is strong. It opens with a concrete situation the reader already lives in, then creates tension with a question. The rhetorical question earns its place here -- this is the one allowed per piece.

---

## 2. Problem Section (4 cards)

**Eyebrow:** "What no one tells you"
**Title:** "The truth about AI coding"

### Violations

**Posturing frame.** "What no one tells you" and "The truth about AI coding" are both banned posturing frames. They signal "I know something you don't" without adding information. Compare to the banned list: "Everyone gets this wrong," "People do not realize," "The real truth is." These two lines hit the same nerve.

**Suggested rewrite for eyebrow + title:**
> "The gaps AI tools leave open"

or simply drop the eyebrow. The card headlines already carry the tension.

### Card 1: "AI forgets things"

> Your AI handles small tasks fine. But as your project grows, it drops details. 45 out of 52 requirements? You won't notice the 7 missing until production breaks.

**Sentence opens with "But."** Hard ban: "No sentences that start with these words: But, And, So, Or."

The concrete number (45 out of 52) is excellent. It grounds the claim before abstraction, which is exactly right.

**Suggested fix:** "Your AI handles small tasks fine. As your project grows, it drops details."

### Card 2: "AI takes shortcuts"

> AI optimizes to look correct. It hardcodes values, skips edge cases, and takes the easy path. Without quality gates, you're trusting vibes over verification.

**Triad.** "hardcodes values, skips edge cases, and takes the easy path" is X, Y, and Z.

**Suggested fix:** "It hardcodes values and skips edge cases." Drop "takes the easy path" -- it restates the card title.

### Card 3: "Fixes create new bugs"

> You patch one thing, another breaks. No system ensures fixes go through quality checks. You're editing live code with no safety net.

Clean. No violations. Good tension. The card does its job.

### Card 4: "Nobody checks the AI's work"

> You are the only quality gatekeeper. One person, reviewing AI-generated code you may not fully understand. That's a recipe for problems.

**"That's a recipe for problems"** is a cliche. It packages the thought as finished, which the guide calls a closure signal. The first two sentences already land the point -- the third adds nothing.

**Suggested fix:** Cut the last sentence entirely. End on "...you may not fully understand." The discomfort is stronger without the summary.

---

## 3. Solution Section (Intro + 3 Cards)

**Eyebrow:** "A better way"
**Title:** "A team of AI specialists, working for you"

### Intro

> Instead of trusting one AI to do everything, Spec Manager uses multiple AI specialists -- each with a different job, each checking the others' work.

**Em dash.** Hard ban.

**Parallel clauses.** "each with a different job, each checking the others' work" is a pseudo-list from parallel clauses. Two "each" clauses in a row.

**Suggested rewrite:**
> Instead of trusting one AI to do everything, Spec Manager assigns different specialists to different jobs. They check each other's work.

### Card 1: Build

> AI writes code from your spec. Every function tracked. Every requirement mapped. If something's unclear, it asks you -- not guesses.

**Parallel openings.** "Every function tracked. Every requirement mapped." Two consecutive sentences with the same opening word and the same grammatical frame (Every + noun + past participle). The guide bans "three consecutive sentences with the same opening word" but also flags "repeated sentence structures even when count is under three" as a soft tell.

**Em dash.** Hard ban.

**Suggested rewrite:**
> AI writes code from your spec. The system tracks every function against the requirements. When something is unclear, it asks you instead of guessing.

### Card 2: Organize

> Working code gets structured properly. Architecture reviewers check the design. Logic bugs get sent back for proper fixes -- not patched.

**Em dash.** Hard ban.

Otherwise solid. The card earns its place.

**Fix:** Replace em dash with a period or restructure: "Logic bugs get sent back for proper fixes instead of patches."

### Card 3: Polish

> Code quality reviewers check for clarity, consistency, correctness. Only code passing all gates reaches your main branch.

**Triad.** "clarity, consistency, correctness" is X, Y, Z.

**Suggested rewrite:** "Code quality reviewers check for clarity and correctness." Two items joined with "and" -- the guide's recommended fix.

---

## 4. How It Works (3 Steps)

**Eyebrow:** "Simple by design"
**Title:** "How it works"

### Step 1: Describe what you want

> Write a spec in plain language. The system tracks every requirement.

Clean. No violations.

### Step 2: AI builds with guardrails

> Multiple AI specialists write, review, and organize your code. Bad code gets sent back. Good code gets promoted.

**Triad (again).** "write, review, and organize" -- the same triad from the hero subhead. This is the third occurrence on the page.

**Metronomic cadence.** Three consecutive short sentences of nearly identical length: 9 words, 6 words, 5 words. All follow subject-verb-object. The guide flags "similar sentence lengths for long stretches" and "three consecutive sentences with the same grammatical frame."

**Suggested rewrite:**
> Multiple AI specialists write and review your code. When something fails a quality gate, it goes back for rework before reaching your branch.

### Step 3: Ship with confidence

> Only code that passes every quality gate reaches your codebase. You can see exactly what was built and why.

Clean. No violations.

---

## 5. Features Bento (6 Cards)

**Eyebrow:** "Built different"
**Title:** "Everything you need to ship with confidence"

### Eyebrow violation

**"Built different"** is a cliche (Apple's old tagline). The guide bans cliches "unless the piece is clearly subverting them." No subversion here.

**Suggested replacement:** Drop it or use something specific like "Under the hood."

### Card 1: "Multiple AIs, not just one"

> Different AI models handle different jobs. Writers, reviewers, architects, quality checkers -- each specialized, each checking the others.

**Em dash.** Hard ban.

**Pseudo-list.** "Writers, reviewers, architects, quality checkers" is a four-item list in prose. The triad ban extends to any list-shaped prose with parallel items.

**Parallel clauses.** "each specialized, each checking the others" -- same pattern as Solution intro.

**Suggested rewrite:**
> Different AI models handle different jobs. A writer produces code. A reviewer catches what the writer missed. Neither ships without passing quality gates.

### Card 2: "Nothing ships without earning it"

> Code moves through quality gates. Failures get demoted back for proper fixes. No shortcuts.

Clean. The staccato closer ("No shortcuts.") is allowed -- this is its one use. Good.

### Card 3: "Every requirement tracked"

> A coverage ledger maps every spec requirement to the code that implements it. Know exactly what's done and what's missing.

Clean. Concrete mechanism (coverage ledger) before the benefit. Well-constructed.

### Card 4: "AI asks, not guesses"

> When something's ambiguous, the system stops and asks you. You make the decision. The AI executes it.

Clean. Slight metronomic risk (three short sentences), but the content varies enough.

### Card 5: "Walk away and come back"

> State persists across sessions. Crash-proof. Pick up exactly where you left off.

Clean. Fragment ("Crash-proof.") works as emphasis.

### Card 6: "Your process, your rules"

> Custom workflows. Choose your AI models. Define how work gets done. Share workflows with your team.

**List-shaped prose / metronomic cadence.** Four consecutive imperative fragments of roughly equal length. This is an imperative chain, and the guide allows "one per piece." Whether this counts as one chain or four separate sentences depends on interpretation, but the cadence reads as a template -- "Do X. Do Y. Do Z. Do W."

**Suggested rewrite:**
> Build custom workflows with the AI models you choose. Your team can share and reuse them.

---

## 6. Differentiator Section (Comparison Lines)

**Eyebrow:** "Not another AI code generator"
**Title:** "The difference is quality control"

### Comparison lines

> They build. / We build AND verify.
> They hope for the best. / We check the work.
> They give you speed. / We give you speed AND confidence.

**Triple contrast pair with identical grammatical frame.** The guide says: "Contrast pairs: use them as a tool, not as a metronome." Three consecutive contrast pairs with the same "They [verb]. / We [verb]." frame is a textbook metronome. The guide also bans "three consecutive sentences with the same grammatical frame" and "three consecutive sentences with the same opening word."

This is the worst violation on the page. It simultaneously trips:
1. Three consecutive sentences starting with "They"
2. Three consecutive sentences starting with "We"
3. Three contrast pairs packed together (tic, not tool)
4. List-shaped prose (parallel clauses: where X happens, where Y happens, where Z happens)

**Suggested rewrite:**

Keep one contrast pair. Make the other points earn their place differently.

> Other tools optimize for speed. Spec Manager optimizes for correctness.
>
> The difference: code that passes through Spec Manager has been reviewed by multiple AI specialists before you see it. Code from other tools has been reviewed by nobody.

Or, if you want to keep the punchy format, cut to two lines max and break the frame:

> They build. We build and verify.
> Their output is unreviewed. Ours passed five quality gates before you saw it.

---

## 7. Pricing (Feature Lists)

### Free (Local)

> Runs on your machine / Full privacy / Bring your own AI keys / Complete feature set

### Hybrid

> Remote management / Local execution / Easier setup / Use your AI subscriptions

### Cloud

> Fully managed / Easiest experience / No setup required / Everything included

Pricing feature lists are inherently list-shaped, and that is fine -- the guide relaxes list-formatting bans for structural UI elements. No prose violations here.

**Tone issue:** "Complete feature set" and "Everything included" are vague. They sound like filler. What does "everything" mean? If the free tier already has the "complete feature set," what does the cloud tier's "everything included" add?

**Suggested fix:** Replace "Complete feature set" with something concrete like "All quality gates and workflows." Replace "Everything included" with "AI keys and hosting included" (if that is the actual differentiator).

---

## 8. FAQ (5 Answers)

### Q1: "Is this just another Cursor/Copilot?"

> No. Those are AI coding assistants -- one AI writes code and you review it. This is a quality pipeline -- multiple AIs write, review, and organize code through gates before it ever reaches you.

**Two em dashes.** Hard ban.

**Triad (fourth occurrence).** "write, review, and organize" again.

**Suggested rewrite:**
> No. Those are AI coding assistants: one AI writes code, then you review it. Spec Manager is a quality pipeline. Multiple AIs write and review code through gates before it reaches you.

### Q2: "Do I need to know how to code?"

> No. You write specs in plain language. The system handles implementation, review, and quality control.

**Triad.** "implementation, review, and quality control" is X, Y, Z.

**Suggested rewrite:** "The system handles implementation and review."

### Q3: "What if I already use Cursor/Copilot?"

> This works alongside your existing tools. It doesn't replace them -- it adds quality control on top. The workflow engine integrates with Claude Code, Cursor, Windsurf, and more.

**Em dash.** Hard ban.

**"and more"** is vague filler. Name the tools or cut the phrase.

**Suggested rewrite:**
> This works alongside your existing tools. It adds quality control on top rather than replacing them. The workflow engine integrates with Claude Code, Cursor, and Windsurf.

### Q4: "Is my code private?"

> The free local version never sends code anywhere except to the AI APIs you configure. Your code stays on your machine.

Clean. Direct. Does its job.

### Q5: "When does it launch?"

> We're building the prototype now. Join the waitlist to be first when we launch.

Clean. Honest. Appropriate brevity.

---

## 9. Final CTA

**Title:** "Ready to ship code you can trust?"

> Join the waitlist and be the first to experience AI-powered code quality.

**"AI-powered code quality"** is generic marketing language. It could describe any product. The rest of the page has been specific -- "multiple AI specialists," "quality gates," "coverage ledger." This line retreats into abstraction at the moment it should be most concrete.

**"be the first to experience"** is filler. It is a posturing phrase that creates no urgency and adds no information.

**Suggested rewrite:**
> Join the waitlist. You will be first to try the quality pipeline when it launches.

Or lean into the tension from the hero:

> Your AI writes the code. Now something checks if it's right. Join the waitlist.

---

## Recurring Issues (Page-Wide)

### 1. The "write, review, and organize" triad appears 4 times

- Hero subhead (line 53)
- How It Works step 2 (line 229)
- Bento card 1 (lines 258-259, variant: "Writers, reviewers, architects, quality checkers")
- FAQ answer 1 (line 431)

This is not just a triad problem. It is a messaging crutch. The page leans on this phrase as a tagline, but the guide is clear: triads in prose fail. The fix is to pick the phrase's strongest version, use it once, and find different angles for the other three occurrences.

### 2. Em dashes appear 8 times

Lines 55, 161, 178, 189, 259, 429-430, 460, and the meta description (line 6, though meta tags are outside the audited copy).

Every single one is a hard ban violation. Replace with periods, colons, or restructured sentences.

### 3. Metronomic cadence in short-sentence sections

The How It Works, Differentiator, and Bento Card 6 sections all exhibit runs of sentences with identical length and frame. Landing pages tolerate more rhythm than essays, but three or more identical frames in a row still reads as a template.

### 4. Posturing / cliche eyebrows

- "What no one tells you" (posturing frame)
- "Built different" (cliche)
- "Not another AI code generator" (defensive framing -- effective here, this one is fine)

---

## Overall Narrative Arc

### Does it create tension?

**Yes, in the hero.** "Your AI writes the code. Who checks if it's right?" is a genuine tension hook. The reader who uses AI coding tools will feel this immediately.

**The Problem section reinforces it well.** Concrete numbers (45/52), specific failure modes (hardcoded values, edge cases), and a direct accusation ("You are the only quality gatekeeper") keep the tension alive.

### Does the hook work?

Yes. The hero headline is the strongest copy on the page. It names a real gap that the target audience lives with daily.

### Is there a reframe?

**Partially.** The reframe is supposed to happen at the Solution section: "Instead of trusting one AI to do everything, use multiple specialists." This is a reframe, but it arrives too quickly and too cleanly. The problem section creates discomfort; the solution section resolves it in one sentence. There is no dwelling in the gap.

A stronger reframe would name why the single-AI approach is structurally broken (not just "it forgets things" but "a single model cannot review its own work the way a single developer cannot QA their own code"). The human analogy is right there -- nobody ships code without review. The page skips this reframe and jumps straight to "here is the answer."

### Does the reader feel the problem?

**For cards 1 and 4, yes.** The "45 out of 52" number and "you are the only quality gatekeeper" both create felt stakes.

**For cards 2 and 3, less so.** "AI takes shortcuts" and "Fixes create new bugs" are stated rather than felt. A concrete example of a shortcut (e.g., "it returns a hardcoded list instead of querying the database") would ground these cards.

### Is there a concrete anchor before abstraction?

**In the hero, no.** The subhead goes immediately abstract ("multiple AI specialists write, review, and organize your code through quality gates"). There is no concrete image of what this looks like in practice.

**In the problem section, yes.** The 45/52 number is a strong concrete anchor.

**In the solution section, no.** The three cards (Build, Organize, Polish) are all described abstractly. What does "architecture reviewers check the design" actually look like? A screenshot, a before/after, or even a one-sentence scenario would help.

### Missing from the arc

1. **No social proof or evidence.** The page makes strong claims about AI failure modes and product capability with zero evidence. No testimonials (understandable for pre-launch), but also no screenshots, no demo, no "here is what this looks like." The guide's evidence toggle applies: cite, label as hypothesis, or give an anecdote.

2. **No stakes escalation.** The problem section lists four problems, but they are presented as equal. A stronger arc would escalate: small annoyance, then bigger risk, then the structural reason this will keep getting worse. The current structure is flat -- four parallel cards, all at the same emotional register.

3. **The Differentiator section is the weakest part of the page.** It arrives after Features (which already established the differentiation) and says less than what came before. The triple contrast pair ("They build. We build AND verify.") is both the worst writing violation and the least informative content. This section should either be cut or reworked into something with actual substance -- a specific comparison, a concrete scenario where the pipeline catches something Cursor would miss.

---

## Summary of Hard Ban Violations

| Violation | Count | Locations |
|-----------|-------|-----------|
| Em dash | 8 | Hero, Solution intro, Build card, Organize card, Bento card 1, FAQ 1, FAQ 3, meta desc |
| Triad in prose | 6 | Hero subhead, Build card, Polish card, How It Works step 2, Bento card 1, FAQ 1, FAQ 2 |
| Sentence starting with "But" | 1 | Problem card 1 |
| Posturing frame | 2 | Problem eyebrow, Problem title |
| Cliche | 1 | Features eyebrow ("Built different") |

## Summary of Soft Tell Violations

| Issue | Count | Locations |
|-------|-------|-----------|
| Parallel clauses (pseudo-list) | 3 | Solution intro, Bento card 1, Differentiator |
| Metronomic cadence | 3 | How It Works step 2, Differentiator, Bento card 6 |
| Vague filler | 3 | Pricing ("Complete feature set", "Everything included"), FAQ 3 ("and more") |
| Closure signal / cliche | 1 | Problem card 4 ("recipe for problems") |
| Repeated sentence structure | 2 | Build card ("Every X. Every Y."), Differentiator ("They X. We Y." x3) |
