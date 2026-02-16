# Visual Direction B: Scroll Narrative Product Tour

**Direction name:** "The Pipeline Story"
**Playbook:** Playbook 2 -- Scroll narrative product tour
**Date:** 2026-02-14

---

## 1. Direction Summary

This direction treats the entire landing page as a single continuous story told in chapters, where scrolling is the act of turning pages. The user descends through a vertical narrative that moves from familiar pain ("things break") to named diagnosis ("nobody checks the AI's work") to revealed mechanism (the three-layer pipeline) to proof and offer. Every section answers exactly one question, and the transition between sections uses a scroll-driven "chapter turn" animation that physically repositions content to signal "a new page has begun." The visual language is restrained and editorial -- dark, calm backgrounds with a single accent gradient used as a narrative device: the violet-to-cyan pipeline gradient appears at the moment of revelation (the solution section) and intensifies as the page progresses toward the CTA, creating a color arc that mirrors the story arc.

The skin wow is the accent gradient used as a narrative marker (not as decoration). The behavior wow is the scroll-driven chapter transition system itself. Everything else stays conventional.

---

## 2. Visual Metaphor

**"The manuscript that reveals its blueprint."**

The page is structured like a technical manuscript -- clean, typographic, editorial. Each chapter opens with a large typographic heading and a quiet background. But as the user scrolls into the solution and mechanism sections, the manuscript "opens up" to reveal the underlying blueprint: a glowing pipeline diagram that lives beneath the surface of the page and becomes progressively more visible. Think of a book where the pages become translucent and you begin to see the engineering diagram printed on a layer beneath.

This metaphor serves two purposes:
1. It makes the "quality pipeline" feel like an underlying system that was always there -- you just needed to look deeper.
2. It creates a natural visual progression: early sections are pure typography on dark backgrounds (the readable surface), while later sections expose more of the glowing pipeline infrastructure (the system beneath).

The pipeline itself is not a dashboard UI or a product screenshot. It is a stylized linear flow diagram -- three connected stages with gates between them -- rendered as thin glowing lines and nodes on a dark field. It appears first as a faint background element in the solution section, then as a fully visible interactive element in the how-it-works section, then as a confident decorative motif in the final CTA section.

---

## 3. Color System

### Background Treatment

The page uses a single continuous dark background that subtly shifts temperature as the narrative progresses:

- **Chapters 1-2 (Hero, Problem):** `#08090e` -- near-black with a cool blue undertone. This is the "cold open" of the story. No warmth, no glow. The user is in the dark, both literally and metaphorically.
- **Chapters 3-4 (Solution, How-it-works):** `#0a0b14` -- fractionally warmer, with a barely perceptible indigo shift. The revelation has begun. If you screenshot chapters 1 and 3 side by side, the difference is visible; in continuous scrolling, it reads as a gradual atmospheric shift, not a hard cut.
- **Chapters 5-8 (Features, Differentiator, Pricing, FAQ):** `#0c0d18` -- the warmest dark, with the indigo undertone most visible. The system has been revealed; the user is inside the pipeline's world now.
- **Chapter 9 (Final CTA):** Returns to `#08090e` but with the pipeline gradient overlay at 8% opacity, creating a "where we started, but transformed" feeling.

**Depth technique:** No flat backgrounds. Each section has a single large radial gradient positioned off-center (never centered -- always biased 20-30% toward one edge) at very low opacity (4-8%). These gradients use the accent palette (violet at early sections, shifting toward cyan at later sections) and create a sense of atmospheric light without competing with content. They are not "glowing orbs" -- they are soft, slow-falloff radial gradients that read as "there is a light source somewhere in this room."

The gradient positions alternate sides: hero gradient biased left, problem gradient biased right, solution gradient biased left. This creates a gentle lateral rhythm as the user scrolls.

### Surface Hierarchy

Three surface levels:

| Level | Background | Border | Usage |
|-------|-----------|--------|-------|
| **Page** | Section background color (see above) | None | Full-width sections |
| **Card** | `rgba(255, 255, 255, 0.03)` | `1px solid rgba(255, 255, 255, 0.06)` | Problem cards, feature cards, pricing cards |
| **Elevated** | `rgba(255, 255, 255, 0.05)` | `1px solid rgba(255, 255, 255, 0.10)` | Active/hovered cards, pipeline stage detail panels |

Cards are not strongly elevated. They are distinguished from the page primarily by their border, not their fill. The fill is barely perceptible -- just enough to register as "a contained region" against the page background. This keeps the editorial feel. Cards should feel like text blocks with a boundary, not floating UI widgets.

### Accent Usage

**Primary accent:** `#7c5cfc` (violet). Used for:
- Chapter numbers (the "01", "02" markers)
- The pipeline gradient's starting color
- CTA button backgrounds
- The accent word in the hero headline (gradient text)
- Active states on interactive elements

**Secondary accent:** `#00d4ff` (cyan). Used for:
- The pipeline gradient's ending color
- Success/verification indicators
- The "passed gate" checkmarks in the pipeline diagram
- Hover states that suggest "verified" or "completed"

**Attention hierarchy:**
1. CTA buttons (solid violet fill + glow) -- loudest
2. Pipeline gates when active (cyan glow) -- second
3. Chapter numbers and eyebrow labels (violet text) -- third
4. Card borders on hover (violet at 40% opacity) -- quietest

Everything else recedes: text is near-white or mid-gray, backgrounds are dark, cards are barely tinted.

### Gradient Strategy

The violet-to-cyan gradient (`linear-gradient(135deg, #7c5cfc 0%, #00d4ff 100%)`) is the narrative gradient. It represents the pipeline -- code entering (violet/raw) and emerging verified (cyan/complete).

**Where it appears:**
- Hero headline accent word: gradient text on "checks" in "Who checks if it's right?"
- Pipeline diagram track: the thin connecting line between stages uses this gradient left-to-right
- Chapter transition dividers: a 1px horizontal line between sections uses this gradient, fading from transparent at edges to full gradient at center, at 30% opacity
- CTA button on hover: the button background shifts from solid violet to this gradient
- Final CTA section: the gradient appears as a large radial glow at 6% opacity behind the form

**Where it does NOT appear:**
- Card backgrounds (no gradient fills on cards)
- Body text (never applied to paragraphs)
- Full-section backgrounds (never a gradient background spanning 100vh)
- Icons (icons are monochrome white or accent solid)

Gradients are always applied to narrow, specific elements -- lines, text runs, button states. They never fill large areas. This keeps the gradient feeling precious and meaningful rather than decorative.

### Ambient Treatment

**Grain overlay:** A film-grain texture at 3% opacity, applied as a fixed full-viewport overlay using an SVG `feTurbulence` filter (`baseFrequency: 0.65`, `numOctaves: 3`), blended with `mix-blend-mode: overlay`. This adds physical texture to the dark backgrounds, preventing the "pure digital flat" feeling. The grain is subtle enough that it is felt rather than seen -- it creates a sense of material without being visible at normal viewing distance.

**No floating orbs or blobs.** Direction B's skin wow is the narrative gradient, not ambient animation. The backgrounds are still and quiet. Motion is reserved entirely for scroll-driven behavior (the behavior wow). Having both moving backgrounds AND scroll-driven content animations would violate the one-wow-per-layer rule.

---

## 4. Typography System

### Font Choices

**Headlines: Inter (variable, weights 600-700)**

Inter is chosen for its geometric neutrality and high legibility at all sizes. Its tight metrics and clean geometry convey precision without coldness. It is the workhorse of modern devtools (Linear, Vercel, Supabase) and reads as "serious tool, made well" to the target audience.

For this direction specifically, Inter's optical sizing axis is critical: at large hero sizes, the letterforms open up slightly for display elegance, while at body sizes they tighten for reading efficiency. This single typeface provides enough range to create the entire hierarchy without a second display font.

**Body: Inter (variable, weights 400-500)**

Same family for consistency. The editorial narrative feel comes from the type scale and spacing, not from font variety. Using one family throughout reinforces the "manuscript" metaphor -- the entire page reads as one continuous document.

**Mono accent: JetBrains Mono (weights 400-500)**

Used sparingly and specifically:
- Pipeline stage labels ("L1: BUILD", "L2: ORGANIZE", "L3: POLISH")
- Inline code references when describing the spec system
- The metric numbers in the proof section ("723 tests", "52/52 requirements")
- Pricing tier prices ("$0", "$15")

JetBrains Mono signals "this is a technical system" without requiring the user to read code. Its appearance marks content as "from the system's world" vs. "from the story's world." This creates a two-voice typographic system: Inter tells the story, JetBrains Mono speaks for the machine.

### Hierarchy Through Size, Weight, Spacing, Color

| Element | Font | Size | Weight | Line Height | Letter Spacing | Color |
|---------|------|------|--------|-------------|----------------|-------|
| Chapter number | JetBrains Mono | 14px | 500 | 1.0 | 0.12em | `#7c5cfc` (accent) |
| Hero headline | Inter | clamp(3rem, 5vw+1rem, 4.5rem) | 700 | 1.1 | -0.03em | `#edeef2` (primary) |
| Section headline | Inter | clamp(2rem, 3vw+0.5rem, 2.75rem) | 700 | 1.2 | -0.02em | `#edeef2` |
| Section subhead | Inter | 1.125rem (18px) | 400 | 1.6 | 0 | `#9496a8` (secondary) |
| Card title | Inter | clamp(1.125rem, 1.5vw+0.25rem, 1.375rem) | 600 | 1.3 | 0 | `#edeef2` |
| Body copy | Inter | 1rem (16px) | 400 | 1.625 | 0 | `#9496a8` |
| Pipeline label | JetBrains Mono | 0.75rem (12px) | 500 | 1.0 | 0.08em | `#edeef2` |
| Metric number | JetBrains Mono | clamp(2rem, 3vw, 3rem) | 700 | 1.1 | -0.02em | `#edeef2` |
| CTA button | Inter | 0.875rem (14px) | 600 | 1.0 | 0.04em | `#ffffff` |
| Friction reducer | Inter | 0.875rem (14px) | 400 | 1.5 | 0 | `#5c5e72` (muted) |

### How Typography Creates the "Chaptered" Narrative Feel

Each chapter (section) opens with a consistent typographic pattern:

1. **Chapter number** (top, left-aligned within the content column): "01", "02", etc. Set in JetBrains Mono at 14px, violet accent color, tracked wide (0.12em). This is the page's primary structural device -- it explicitly tells the user "this is a sequence, you are progressing."

2. **Eyebrow label** (below the chapter number, same alignment): A short categorical phrase in Inter at 12px, weight 600, tracked at 0.08em, uppercase, secondary text color. Example: "THE PROBLEM", "THE SYSTEM", "HOW IT WORKS".

3. **Section headline** (below the eyebrow, same alignment): The main statement, left-aligned (NOT centered -- this is a manuscript, not a presentation). Large, bold, tight leading.

4. **Section subhead** (below the headline, same alignment): One to two sentences of supporting context. Regular weight, relaxed leading, secondary text color. Maximum width: 640px (to maintain comfortable line length for reading).

This left-aligned, sequential typographic structure is what makes the page feel like chapters rather than slides. Centering all text creates a "presentation deck" feel. Left-alignment within a consistent column creates a "reading" feel. The chapter numbers make the sequence explicit.

**Exception:** The hero section centers its headline and subhead. This is the only centered text on the page. The centering marks the hero as the "title page" of the manuscript. Once the user begins scrolling into Chapter 01 (Problem), the alignment shifts left and stays left for the remainder of the page.

---

## 5. Shape and Composition

### Dominant Shape Primitives

**Rounded rectangles with 12px radius** as the single dominant shape. Applied to:
- All cards (problem, feature, pricing, pipeline stage)
- Buttons (12px radius, not pill-shaped)
- Input fields
- The pipeline gate icons (rounded square, 12px radius)

**Thin horizontal lines** as the secondary shape. Applied to:
- Chapter dividers (1px, gradient fill at 30% opacity)
- The pipeline track (2px, gradient fill)
- Card borders (1px, subtle white at 6% opacity)

No circles, no blobs, no irregular shapes. The rounded rectangle + thin line vocabulary creates a clean, technical, editorial aesthetic. The 12px radius is soft enough to feel modern without becoming playful (pill shapes, full-round corners).

### Card Treatment

Cards are containers, not feature showcases. They are restrained:

```
Background: rgba(255, 255, 255, 0.03)
Border: 1px solid rgba(255, 255, 255, 0.06)
Border-radius: 12px
Padding: 32px
Box-shadow: none (resting state)
```

On hover:
```
Background: rgba(255, 255, 255, 0.05)
Border: 1px solid rgba(124, 92, 252, 0.30)
Box-shadow: 0 0 30px rgba(124, 92, 252, 0.08)
Transition: all 250ms cubic-bezier(0.25, 0.1, 0.25, 1.0)
```

Cards do not lift (no translateY on hover). They do not scale. The only change is a border color shift to accent-violet and a very subtle glow around the border. This keeps the "manuscript" feeling -- elements don't float off the page.

### Section Layout Patterns

The page uses a single content column: `max-width: 760px` for text-heavy sections (problem, differentiator, FAQ, CTA), `max-width: 1100px` for sections with grids (features, pricing, how-it-works). Centered on the page with `margin: 0 auto`.

**Chapter layout structure (repeated for each section):**

```
[Full-width section background]
  [Content column, 760px or 1100px]
    [Chapter number + eyebrow, left-aligned]
    [24px gap]
    [Section headline, left-aligned]
    [16px gap]
    [Section subhead, left-aligned, max-width 640px]
    [48px gap]
    [Section-specific content: cards, grid, pipeline, form]
  [/Content column]
[/Full-width section background]
```

### Visual Rhythm and Whitespace

**Section padding:** Each section has 120px top padding and 120px bottom padding at desktop (reduced to 80px at tablet, 64px at mobile). This generous vertical whitespace is essential to the "chapter" feeling -- each section needs breathing room to feel like its own page.

**Between headline and content:** 48px. This gap separates the "what this chapter is about" from "the chapter's content."

**Between cards in a grid:** 24px gap. Tight enough to read as a group, loose enough for each card to breathe.

**Content column left margin on desktop:** The 760px column is centered, creating wide margins on both sides. These empty margins are part of the design -- they create the "manuscript margin" feeling and prevent the page from feeling crammed.

### How the Page Signals "There Is More Below"

At each chapter break, the following signals continuation:

1. **The chapter divider line:** A 1px horizontal line using the pipeline gradient, fading from transparent at left/right edges to visible at center, at 30% opacity. This line sits in the gap between sections and explicitly says "a boundary was crossed, but the sequence continues."

2. **Content fade:** The last 80px of each section fades the background very subtly (2% opacity shift) to suggest the environment is transitioning. This is not a harsh gradient mask -- it is a barely perceptible atmospheric shift.

3. **Partial visibility of next chapter number:** At the bottom of each section, the top portion of the next chapter's "01" / "02" number is visible (cropped by the viewport bottom). This peek creates a "there's more" signal without requiring a dedicated scroll arrow.

4. **The hero section specifically** includes a small scroll indicator at the bottom: a thin vertical line (1px wide, 40px tall, white at 30% opacity) with a small dot that travels down the line over 2 seconds, then resets. This is the only looping animation on the page and it appears only in the hero. Below this line, the text "scroll" in Inter at 11px, muted color. This indicator fades out (opacity 0) once the user scrolls past 100px.

---

## 6. Motion System

### The ONE Wow in Skin: The Narrative Gradient

The pipeline gradient (`linear-gradient(135deg, #7c5cfc, #00d4ff)`) is used as a story device that intensifies as the user progresses through the page. In the hero, it appears only on the accent word. In the solution section, it appears on the pipeline diagram's track line. In the features section, it tints the chapter divider. In the final CTA, it appears as a background glow. This progression is NOT animated -- it is structural. The gradient simply appears in more places as the page deepens, creating a cumulative visual effect tied to scroll progress.

### The ONE Wow in Behavior: Scroll-Driven Chapter Transitions

This is the direction's signature behavior. Between each major section, when the user scrolls past a chapter boundary, the outgoing section's content fades slightly while the incoming section's content slides up with a subtle parallax offset.

**Implementation approach:** CSS Scroll-Driven Animations (using `animation-timeline: view()`) with JavaScript Intersection Observer as fallback.

**The chapter transition (between every pair of sections):**

As the chapter divider line enters the viewport:
- **The divider line itself:** Draws from center outward (using a CSS mask or clip-path that expands from `inset(0 50%)` to `inset(0 0)`) over the scroll range of 100px (divider enters viewport bottom to divider reaches 30% from bottom). Duration is scroll-driven, not time-driven. Easing: `cubic-bezier(0.0, 0.0, 0.2, 1.0)` (decelerate). The line is 100% of the content column width, gradient-filled.

- **The outgoing section's last content block:** Fades from `opacity: 1` to `opacity: 0.4` over the same 100px scroll range. Does NOT translate. Stays in place.

- **The incoming section's chapter number + eyebrow + headline:** These three elements start at `opacity: 0` and `translateY(24px)` when they are below the viewport. As they scroll into view (from 0% visible to 20% visible), they fade in and translate to their final position. This takes approximately 200px of scroll distance. Easing: `cubic-bezier(0.0, 0.0, 0.2, 1.0)` (decelerate). The three elements stagger: chapter number appears first, eyebrow 60ms later (in scroll-distance equivalent), headline 60ms after that.

- **The incoming section's body content (cards, grids, etc.):** Starts at `opacity: 0` and `translateY(32px)`. Animates in when the content reaches 15% viewport visibility. Same easing. If multiple cards, stagger by 80ms equivalent per card, maximum 6 items staggered (7+ animate simultaneously).

### Scroll-Trigger Strategy

All animations are tied to element visibility within the viewport using Intersection Observer thresholds (CSS `animation-timeline: view()` where supported, JS fallback otherwise).

| Element | Trigger Point | Animation | Scroll Distance to Complete | Easing |
|---------|--------------|-----------|---------------------------|--------|
| Chapter divider line | Enters viewport bottom | Draw from center outward | 100px of scroll | Decelerate |
| Outgoing section content | Divider enters viewport | Fade to 0.4 opacity | 100px of scroll | Decelerate |
| Chapter number | 0% visible | Fade in + translate up 24px | 150px of scroll | Decelerate |
| Eyebrow label | 0% visible (stagger +60ms) | Fade in + translate up 24px | 150px of scroll | Decelerate |
| Section headline | 0% visible (stagger +120ms) | Fade in + translate up 24px | 150px of scroll | Decelerate |
| Section subhead | 5% visible | Fade in + translate up 16px | 120px of scroll | Decelerate |
| Individual cards | 15% visible | Fade in + translate up 32px | 200px of scroll | Decelerate |
| Card stagger | Each subsequent card | +80ms delay (scroll equivalent) | Same | Same |
| Pipeline gate nodes | 20% visible | Scale from 0.9 to 1.0 + border glow on | 150px of scroll | Spring (0.34, 1.56, 0.64, 1.0) |
| Pipeline track line | Left gate 30% visible | Draw left-to-right (clip-path) | 300px of scroll | Linear |
| Hero scroll indicator | Page load | Dot travels down line | 2s loop (time-based, the ONLY looping animation) | Linear |
| Hero scroll indicator | User scrolls 100px | Fade out to opacity 0 | Instant (250ms transition) | Standard |

### Chapter Transition Treatment (Detailed)

Here is exactly what the user sees at the boundary between the Problem section and the Solution section (this pattern repeats for all boundaries):

**Scroll position 0 (problem section fully visible, solution below viewport):**
The user sees the last problem card. Below the visible viewport, the chapter divider line and the solution section content are waiting at `opacity: 0`.

**Scroll position +50px (divider line enters the bottom of the viewport):**
The divider line begins drawing from its center outward. At this point it is 50% drawn -- a short gradient-filled segment visible at the center of the content column. The problem section's last visible content block begins fading (currently at `opacity: 0.85`).

**Scroll position +100px (divider line is 30% from viewport bottom):**
The divider line is fully drawn -- a complete gradient line spanning the content column width. The problem section's last content is at `opacity: 0.4`. The solution section's chapter number "03" has just entered the viewport bottom at `opacity: 0` and `translateY(24px)`.

**Scroll position +150px:**
The chapter number "03" is at `opacity: 0.6` and `translateY(10px)`. The eyebrow "THE SYSTEM" has entered the viewport and is at `opacity: 0.3` and `translateY(18px)`.

**Scroll position +250px:**
All three header elements (number, eyebrow, headline) are at full opacity and final position. The solution section's body content (pipeline diagram) is beginning to fade in from below.

**Scroll position +450px:**
The solution section is fully visible. The transition is complete.

### Stagger and Timing

**Stagger rule:** When multiple sibling elements enter the viewport together (cards in a grid, list items, pipeline stages), each subsequent element delays its animation start by 80ms (time-based) or the scroll equivalent (~16px of additional scroll distance before triggering).

**Maximum stagger group:** 6 elements. If a section has more than 6 items entering at once, items 7+ animate simultaneously with item 6.

**No concurrent stagger groups:** If two groups of staggered elements are visible in the viewport simultaneously, the first group completes before the second begins. This is naturally handled by scroll position -- the user must scroll past one group to reach the next.

**No looping animations** except the hero scroll indicator dot. All scroll-triggered animations fire once. Once an element reaches its final state, it stays there permanently (the Intersection Observer disconnects after triggering, or the CSS animation `fill-mode` is set to `forwards`).

---

## 7. Section-by-Section Visual Treatment

### Section 1: Hero

**Question answered:** "What is this? Is it for me?"

**Background treatment:**
`#08090e` base. A single radial gradient positioned at 30% from left, 40% from top: `radial-gradient(ellipse 70% 50% at 30% 40%, rgba(124, 92, 252, 0.06) 0%, transparent 60%)`. This creates a barely perceptible violet atmospheric light on the left side of the hero. No floating orbs, no blobs, no mesh gradients. Just one quiet light source.

**Layout approach:**
Full viewport height (`min-height: 100vh`). Content centered both horizontally and vertically:

```
[Centered content block, max-width: 800px]
  [Headline: "Your AI writes the code." (line break) "Who checks if it's right?"]
  [16px gap]
  [Subhead: "Multiple AI specialists write, review, and organize your code through quality gates -- so nothing ships broken."]
  [32px gap]
  [CTA group: email input (360px wide) + "Join the Waitlist" button, inline at desktop, stacked at mobile]
  [12px gap]
  [Friction reducer: "Be first when we launch. No credit card needed." -- muted text]
[/Centered content block]

[Scroll indicator at bottom center, 48px above viewport bottom]
```

The word "checks" in the headline uses the pipeline gradient as text fill (`background-clip: text`), making it the single gradient-text element in the hero. This is the narrative gradient's first appearance.

**Key visual elements:**
- The gradient-text accent word ("checks")
- The scroll indicator (vertical 1px line, 40px tall, with traveling dot)
- The CTA button with a subtle violet glow (`box-shadow: 0 0 20px rgba(124, 92, 252, 0.30), 0 0 60px rgba(124, 92, 252, 0.12)`)

**Scroll-triggered behavior:**
None. The hero is static. Content is visible on page load with no entrance animation (the hero must be immediately readable -- no fade-in delay). The only motion is the scroll indicator's traveling dot (2s loop, linear).

**Chapter transition to next section:**
As the user scrolls down, the hero content remains in place (no parallax). When the user has scrolled 60% of the viewport height, the hero content begins fading to `opacity: 0.4` over the next 200px of scroll. The chapter divider line between hero and problem section draws in as described in section 6. The "01" chapter number of the problem section peeks up from the bottom.

---

### Section 2: Problem

**Question answered:** "Wait, I've felt this exact thing."

**Background treatment:**
`#08090e` base (same as hero -- no visible change yet). Radial gradient positioned at 70% from left, 50% from top: `radial-gradient(ellipse 60% 40% at 70% 50%, rgba(124, 92, 252, 0.04) 0%, transparent 50%)`. Slightly more subtle than the hero gradient and positioned on the opposite side, creating the lateral rhythm.

**Layout approach:**
Narrow content column (760px). Left-aligned text.

```
[Chapter number: "01" -- violet, JetBrains Mono]
[Eyebrow: "THE PROBLEM" -- uppercase, tracked wide, secondary color]
[24px gap]
[Headline: "AI-generated code has a quality problem nobody talks about"]
[16px gap]
[Subhead: 1-2 sentences of context -- secondary color, max-width 640px]
[48px gap]
[4 problem cards, single column, stacked vertically with 20px gaps]
```

The problem cards are single-column, NOT a grid. Each card spans the full 760px column width. This forces the user to read them sequentially -- one problem at a time, like paragraphs in a story. A 2x2 grid would allow skipping; the single column enforces the narrative sequence.

**Card structure (each problem card):**

```
[Card: 760px wide, 12px radius, subtle border]
  [Left side: card title in primary text color, 18px, weight 600]
  [8px gap]
  [Card description in secondary text color, 16px, weight 400, line-height 1.625]
[/Card]
```

No icons on the problem cards. Icons would add visual noise and imply solutions. The problems should feel like plain-language observations -- text-forward, editorial.

**Key visual elements:**
- The "01" chapter number in violet monospace
- The four text-heavy cards, unadorned
- The stacking layout that forces sequential reading

**Scroll-triggered behavior:**
- Chapter header (number + eyebrow + headline) fades in with stagger as described in section 6
- Each problem card fades in + translates up 32px as it enters the viewport (15% threshold)
- Cards stagger: card 1 immediately, card 2 at +80ms delay, card 3 at +160ms, card 4 at +240ms
- All animations use decelerate easing, 600ms duration equivalent in scroll distance

**Chapter transition to next section:**
Same pattern as described in section 6. The fourth problem card fades to 0.4 opacity as the divider line draws in. The "02" chapter number of the solution section peeks up.

---

### Section 3: Solution (The Reveal)

**Question answered:** "Oh -- there's an actual system for this?"

**Background treatment:**
`#0a0b14` -- the background shifts fractionally warmer/deeper for the first time. This is the "environment change" moment. The radial gradient is positioned at 50% from left, 30% from top: `radial-gradient(ellipse 80% 60% at 50% 30%, rgba(124, 92, 252, 0.08) 0%, rgba(0, 212, 255, 0.03) 40%, transparent 65%)`. This is the first gradient that includes cyan, foreshadowing the pipeline. It is still very subtle -- a whisper of color on a dark field.

**Layout approach:**
Content column expands to 1100px for this section to accommodate the pipeline diagram.

```
[Chapter number: "02"]
[Eyebrow: "THE SYSTEM"]
[24px gap]
[Headline: "Multiple AI specialists, each with a different job, each checking the others' work"]
[16px gap]
[Subhead: "Instead of trusting one AI to do everything..."]
[64px gap]
[Pipeline diagram: three stages connected by a track line]
[40px gap]
[Below the pipeline: a single sentence -- "Code earns its way to your branch. Nothing skips the line."]
```

**Pipeline diagram specification:**

The pipeline diagram is a horizontal flow of three stage cards connected by a thin track line.

```
[Stage 1: BUILD]---[Gate]---[Stage 2: ORGANIZE]---[Gate]---[Stage 3: POLISH]--->[Output]
```

Each **stage card** is a rounded rectangle (12px radius), 280px wide, 180px tall:
- Background: `rgba(255, 255, 255, 0.04)`
- Border: `1.5px solid rgba(255, 255, 255, 0.08)`
- Inside the card:
  - Layer label: "L1" in JetBrains Mono, 12px, violet accent
  - Stage name: "BUILD" in JetBrains Mono, 14px, weight 500, primary text color, tracked at 0.06em
  - 12px gap
  - Stage description: 2 lines of Inter at 14px, secondary text color
  - Example: "AI writes code from your spec. Every function tracked. Every requirement mapped."

Each **gate** is a small diamond shape (24px, rotated 45 degrees), positioned on the track line between stages:
- Border: `1.5px solid rgba(255, 255, 255, 0.10)` (inactive)
- When activated by scroll: border transitions to `1.5px solid rgba(0, 212, 255, 0.60)` + `box-shadow: 0 0 12px rgba(0, 212, 255, 0.30)`

The **track line** connecting all elements is 2px tall, using the pipeline gradient (`linear-gradient(90deg, #7c5cfc, #00d4ff)`). This is the narrative gradient's second appearance and its most prominent one -- it is now a visible structural element, not just text coloring.

The **output** indicator at the right end of the track is a small checkmark icon inside a rounded square (24px), border in success green (`#34d399`).

**Mobile adaptation:** At viewports below 768px, the pipeline rotates to vertical. Stage cards stack top to bottom, the track line becomes a vertical 2px line on the left side, and gates sit on this vertical line between cards.

**Key visual elements:**
- The first appearance of the pipeline diagram (the metaphor made visible)
- The gradient track line (narrative gradient in structural form)
- The gate diamonds that will glow cyan when activated

**Scroll-triggered behavior:**
1. Pipeline stage cards fade in + translate up 32px, staggered left to right (80ms per card) -- triggered at 20% visibility
2. The track line draws from left to right using a `clip-path: inset(0 100% 0 0)` that animates to `clip-path: inset(0 0 0 0)` over 300px of scroll distance -- triggered when the first stage card reaches 30% visibility
3. Gate diamonds scale from 0.9 to 1.0 with spring easing as the track line reaches them -- triggered by the track line's progress (gate 1 at ~33% track drawn, gate 2 at ~66%)
4. Output checkmark pops in with spring easing (`scale: 0 to 1`, 400ms equivalent) when track line is fully drawn

**Chapter transition to next section:**
The pipeline diagram fades to 0.4 as the divider draws. This section has the longest content so the diagram has time to be fully appreciated before the next chapter begins.

---

### Section 4: How It Works

**Question answered:** "OK, what do I actually DO?"

**Background treatment:**
`#0a0b14` (same as solution section -- no shift). Radial gradient biased to the right: `radial-gradient(ellipse 50% 40% at 75% 50%, rgba(0, 212, 255, 0.04) 0%, transparent 50%)`. Now the ambient gradient is cyan-dominant, reflecting the pipeline's "output" end.

**Layout approach:**
Content column at 1100px. Three steps in a horizontal row at desktop, vertical stack at mobile.

```
[Chapter number: "03"]
[Eyebrow: "HOW IT WORKS"]
[24px gap]
[Headline: "Three steps. You handle one."]
[16px gap]
[Subhead: "You describe what you want. The system handles everything else."]
[56px gap]
[Three step cards in a horizontal row, 24px gap between]
```

**Step card structure (each):**

```
[Card: ~340px wide (flex: 1), 12px radius, subtle border]
  [Step number: "1" in JetBrains Mono, 48px, weight 700, violet accent -- fills the top of the card]
  [16px gap]
  [Step title: "Describe what you want" in Inter, 18px, weight 600, primary text]
  [8px gap]
  [Step description: "Write a spec in plain language. The system tracks every requirement." in Inter, 15px, weight 400, secondary text]
[/Card]
```

Step 1 has a violet-tinted left border (`border-left: 3px solid rgba(124, 92, 252, 0.40)`).
Step 2 has a blended-tinted left border (`border-left: 3px solid rgba(167, 139, 250, 0.40)`).
Step 3 has a cyan-tinted left border (`border-left: 3px solid rgba(0, 212, 255, 0.40)`).

This color progression on the left borders echoes the pipeline gradient: violet (input) to cyan (verified output).

**Key visual elements:**
- The large step numbers in violet monospace
- The color-progressive left borders
- The simplicity -- three cards, minimal text

**Scroll-triggered behavior:**
- Chapter header fades in with stagger
- The three step cards fade in + translate up 32px, staggered left to right (80ms each)
- The left border on each card transitions from `opacity: 0` to full opacity 200ms after the card itself finishes its entrance, creating a subtle "accent arrives after content" effect

**Chapter transition to next section:**
Standard chapter transition pattern.

---

### Section 5: Social Proof

**Question answered:** "Is this real?"

**Background treatment:**
`#0c0d18` -- the warmest dark. Radial gradient biased left: `radial-gradient(ellipse 60% 40% at 25% 50%, rgba(124, 92, 252, 0.05) 0%, transparent 50%)`.

**Layout approach:**
Narrow content column (760px). This section is intentionally compact -- it does not need a full chapter treatment because the product is pre-launch. Honesty about pre-launch status IS the proof strategy.

```
[Chapter number: "04"]
[Eyebrow: "BUILT WITH RIGOR"]
[24px gap]
[Headline: "We're building this the way we think software should be built"]
[16px gap]
[Subhead: "Pre-launch and honest about it. Here's what we can show you today."]
[48px gap]
[Three metric cards in a horizontal row, 24px gap]
[32px gap]
[Builder credibility paragraph]
[32px gap]
[Integration strip: small logos/text for Claude Code, Cursor, Windsurf]
```

**Metric card structure:**

```
[Card: ~230px wide, 12px radius, subtle border]
  [Metric number: "723" in JetBrains Mono, clamp(2rem, 3vw, 3rem), weight 700, primary text]
  [4px gap]
  [Metric label: "tests passing" in Inter, 14px, weight 400, secondary text]
[/Card]
```

Three metrics: "723 tests passing", "52/52 requirements tracked", "25+ years building tools".

The builder credibility section is a simple paragraph (not a card): "Built by Nestharus -- 25 years of building developer tools, frameworks, and systems. Currently using Spec Manager to build Spec Manager." In Inter at 16px, secondary text color.

The integration strip is a row of text labels (not logos, since we may not have logo assets): "Works with: Claude Code, Cursor, Windsurf" in Inter at 14px, each tool name in primary text color, separated by subtle vertical bars (1px, 16px tall, white at 10% opacity).

**Key visual elements:**
- The metric numbers in large monospace (signals "real data")
- The honest framing ("pre-launch and honest about it")
- The compact, minimal treatment (no false proof inflation)

**Scroll-triggered behavior:**
- Chapter header fades in with stagger
- Metric cards fade in + translate up 32px, staggered (80ms each)
- Metric numbers themselves count up from 0 to their final value over 800ms using `ease-out` timing -- this is the ONE non-scroll animation in this section (triggered by scroll visibility, but the count-up itself is time-based)
- Builder paragraph and integration strip fade in with standard entrance

**Chapter transition to next section:**
Standard pattern.

---

### Section 6: Features

**Question answered:** "What specifically do I get?"

**Background treatment:**
`#0c0d18` (same as proof section). Radial gradient biased right: `radial-gradient(ellipse 50% 40% at 70% 40%, rgba(0, 212, 255, 0.04) 0%, transparent 50%)`.

**Layout approach:**
Wide content column (1100px). Six feature cards in a 2-column grid at desktop (3 rows of 2), single column at mobile.

```
[Chapter number: "05"]
[Eyebrow: "CAPABILITIES"]
[24px gap]
[Headline: "What the pipeline gives you"]
[48px gap]
[2x3 grid of feature cards, 24px gap]
```

**Feature card structure:**

```
[Card: 12px radius, subtle border, padding 32px]
  [Icon: 24px monoline icon in secondary text color -- NOT accent colored]
  [16px gap]
  [Card title: benefit-oriented headline, Inter 18px weight 600, primary text]
  [8px gap]
  [Card description: 2 lines max, Inter 15px weight 400, secondary text]
[/Card]
```

Icons are simple, monoline, 24px. They use secondary text color (`#9496a8`) at rest. On card hover, the icon transitions to accent violet (`#7c5cfc`) over 250ms. This is the only color change on hover besides the border glow.

The six features:
1. "Multiple AIs, not just one" (icon: users/group)
2. "Nothing ships without earning it" (icon: shield-check)
3. "Every requirement tracked" (icon: list-checks)
4. "AI asks, not guesses" (icon: message-question)
5. "Walk away and come back" (icon: save/disk)
6. "Your process, your rules" (icon: sliders)

**Key visual elements:**
- The 2-column grid (wider layout, more visual density)
- Icon-to-violet transition on hover
- The benefit-first card titles

**Scroll-triggered behavior:**
- Chapter header fades in with stagger
- Feature cards fade in + translate up 32px, staggered in reading order (top-left, top-right, middle-left, middle-right, bottom-left, bottom-right) with 80ms between each
- On card hover: border transitions to accent, icon transitions to violet, subtle glow appears (all 250ms, standard easing)

**Chapter transition to next section:**
Standard pattern.

---

### Section 7: Differentiator

**Question answered:** "How is this different from Cursor/Copilot?"

**Background treatment:**
`#0c0d18`. Radial gradient centered: `radial-gradient(ellipse 70% 50% at 50% 50%, rgba(124, 92, 252, 0.05) 0%, transparent 55%)`. Centered because this section is about clarity and direct comparison -- no lateral bias.

**Layout approach:**
Narrow content column (760px). Pure typography -- no cards, no grid, no diagram. This section lives or dies on the strength of its copy and the authority of its typographic presentation.

```
[Chapter number: "06"]
[Eyebrow: "THE DIFFERENCE"]
[24px gap]
[Headline: "Not another AI code generator"]
[48px gap]
[Large statement: "Other AI tools help you write code faster." -- Inter, 24px, weight 400, secondary text]
[16px gap]
[Large statement: "We make sure it's right." -- Inter, 24px, weight 700, primary text, with "right" in accent gradient text]
[48px gap]
[Three comparison pairs, stacked vertically with 24px gap]
```

**Comparison pair structure:**

Each pair is two lines, not a card:
```
[Line 1: "They build." -- Inter, 18px, weight 400, muted text color]
[Line 2: "We build AND verify." -- Inter, 18px, weight 600, primary text color]
[24px gap before next pair]
```

The contrast between muted and primary text creates the comparison without needing a table, columns, or visual complexity.

**Key visual elements:**
- The large typographic contrast between "write code faster" (secondary, light weight) and "make sure it's right" (primary, bold, gradient accent)
- The comparison pairs using only weight and color for contrast
- The absence of any visual chrome -- this is pure editorial

**Scroll-triggered behavior:**
- Chapter header fades in with stagger
- The large statements fade in sequentially: "Other AI tools..." first, then 200ms later (scroll equivalent) "We make sure it's right" fades in with a slightly longer translateY (40px instead of 24px) to give it more dramatic entrance
- Comparison pairs fade in staggered, 120ms between each pair

**Chapter transition to next section:**
Standard pattern.

---

### Section 8: Pricing

**Question answered:** "What does it cost? Can I try it for free?"

**Background treatment:**
`#0c0d18`. Radial gradient biased left: `radial-gradient(ellipse 50% 40% at 30% 50%, rgba(0, 212, 255, 0.04) 0%, transparent 50%)`.

**Layout approach:**
Content column at 1100px. Three pricing cards in a horizontal row, equal width. At mobile: single column stack.

```
[Chapter number: "07"]
[Eyebrow: "PRICING"]
[24px gap]
[Headline: "Start free. Scale when you're ready."]
[48px gap]
[Three pricing cards, horizontal row, 24px gap]
[40px gap]
[CTA: "Join the Waitlist" button, centered]
[12px gap]
[Friction reducer text, centered]
```

**Pricing card structure:**

```
[Card: ~340px wide, 12px radius, subtle border, padding 32px]
  [Tier label: "FREE" in JetBrains Mono, 12px, weight 500, tracked 0.08em, secondary text]
  [8px gap]
  [Price: "$0" in JetBrains Mono, clamp(2rem, 3vw, 2.5rem), weight 700, primary text]
  [4px gap]
  [Price qualifier: "forever" or "/month" in Inter, 14px, weight 400, muted text]
  [24px gap]
  [Feature list: 3-4 bullet items, each: "Check" icon (12px, success green) + text (Inter, 14px, secondary)]
  [24px gap]
  [Availability badge: "Available at launch" in Inter, 12px, weight 500, inside a pill (rounded-full, subtle border)]
[/Card]
```

The Free tier card has a slightly brighter border (`rgba(255, 255, 255, 0.10)` instead of 0.06) to make it stand out as the recommended option. No gradient borders, no special backgrounds. Just a fractionally more visible border.

**Key visual elements:**
- Prices in large monospace
- The Free tier's subtle emphasis through border brightness
- The CTA button below the pricing grid (not inside individual cards)

**Scroll-triggered behavior:**
- Chapter header fades in with stagger
- Pricing cards fade in + translate up 32px, staggered (80ms each, left to right)
- CTA button fades in last, 200ms after the last card

**Chapter transition to next section:**
Standard pattern.

---

### Section 9: FAQ

**Question answered:** "What about [my specific concern]?"

**Background treatment:**
`#0a0b14` (shifts back to slightly cooler -- the page is "winding down"). No radial gradient in this section. Clean, unadorned dark background. The FAQ is a utility section; it should feel calm and functional, not atmospheric.

**Layout approach:**
Narrow content column (760px). Accordion-style FAQ items.

```
[Chapter number: "08"]
[Eyebrow: "QUESTIONS"]
[24px gap]
[Headline: "What you might be wondering"]
[48px gap]
[5 FAQ items, stacked vertically, 1px divider lines between]
```

**FAQ item structure:**

```
[Question row: full width, clickable]
  [Question text: Inter, 16px, weight 500, primary text -- left aligned]
  [Toggle icon: "+" rotates to "x" on open -- 16px, secondary text color, right aligned]
[/Question row]
[Answer panel: revealed on click, slides down]
  [Answer text: Inter, 16px, weight 400, secondary text, line-height 1.625, max-width 640px]
  [Top padding: 12px, bottom padding: 24px]
[/Answer panel]
[1px divider: rgba(255, 255, 255, 0.06)]
```

The answer panel opens with a height transition: `max-height: 0` to `max-height: 300px` (or measured height), `overflow: hidden`, 400ms, decelerate easing. The toggle icon rotates 45 degrees over 250ms, standard easing.

**Key visual elements:**
- Clean accordion with minimal decoration
- Thin divider lines (consistent with the chapter divider vocabulary)
- The absence of cards (FAQ items are text rows, not boxed)

**Scroll-triggered behavior:**
- Chapter header fades in with stagger
- FAQ items fade in staggered (80ms each), translate up 16px (smaller translate than cards because FAQ items are simpler/lighter)
- Accordion open/close is interaction-driven (click), not scroll-driven

**Chapter transition to next section:**
Standard pattern, but the outgoing fade is stronger (FAQ fades to `opacity: 0.2` instead of 0.4) because the final CTA should feel like a clean, fresh final page.

---

### Section 10: Final CTA

**Question answered:** "OK, what do I do now?"

**Background treatment:**
`#08090e` (returns to the hero's color -- "full circle"). The narrative gradient appears as a radial glow: `radial-gradient(ellipse 80% 60% at 50% 40%, rgba(124, 92, 252, 0.08) 0%, rgba(0, 212, 255, 0.04) 40%, transparent 65%)`. This is the gradient's largest and most visible background application on the entire page -- it has earned this moment through its restrained use earlier. The effect is that the final CTA section feels subtly "warmer" and more inviting than the rest of the page.

**Layout approach:**
Narrow content column (760px). Centered text (echoing the hero's centered treatment -- "title page" bookend).

```
[Centered content block]
  [Headline: "Ship AI code you can trust" -- Inter, clamp(2rem, 3vw+0.5rem, 2.75rem), weight 700, centered]
  [16px gap]
  [Subhead: "Join the waitlist. Be first when we launch." -- Inter, 18px, weight 400, secondary text, centered]
  [32px gap]
  [Email input + CTA button, inline at desktop, stacked at mobile, centered]
  [12px gap]
  [Friction reducer: "No credit card needed. Just your email." -- muted text, centered]
[/Centered content block]
```

**Key visual elements:**
- The centered layout echoing the hero (manuscript "endcap")
- The radial gradient glow (the narrative gradient's final, largest appearance)
- The CTA button with its violet glow

**Scroll-triggered behavior:**
- Headline fades in + translate up 24px
- Subhead fades in 80ms later
- Form fades in 160ms later
- The CTA button glow pulses once (opacity 0.3 to 0.5 and back) after the form is fully visible, drawing final attention. This is a one-shot pulse, not a loop. Duration: 1.5s, standard easing.

**Chapter transition to next section:**
None. This is the last section. Below it is the footer with minimal navigation and the brand wordmark in gradient text.

---

## 8. Strengths and Risks

### Strengths

**1. Clear narrative structure.** The chapter numbering, left-aligned typography, and consistent section pattern make the page's structure immediately legible. Users always know where they are in the story and that more is coming. This directly addresses the "illusion of completeness" risk identified in the visual audit.

**2. Restraint enables emphasis.** By keeping most of the page typographic and dark, the moments where the pipeline gradient appears (hero accent word, solution diagram track, chapter dividers, final CTA glow) carry genuine visual weight. The gradient is a story device with a narrative arc, not wallpaper.

**3. Strong performance characteristics.** No 3D, no heavy JavaScript animation libraries, no video, no floating orbs with blur filters. The motion system is entirely CSS-driven (scroll timelines + transitions + Intersection Observer fallback). The heaviest visual element is the grain overlay SVG filter. This direction should comfortably pass Core Web Vitals: LCP under 2.5s, INP under 200ms, CLS near zero.

**4. Mobile-friendly by default.** The single-column editorial layout is already mobile-appropriate. The pipeline diagram rotates to vertical at 768px. All scroll animations use the same triggers on mobile (Intersection Observer does not depend on viewport width). No horizontal scrolling, no complex grid that collapses awkwardly.

**5. Sequential reading enforced.** The single-column problem cards, the left-aligned text, and the chapter numbering push users to read in order. This matters for a novel product concept that requires the user to understand the problem before the solution makes sense.

**6. Typography does the heavy lifting.** By investing in a strong type hierarchy (chapter numbers in mono, headlines in bold Inter, body in regular Inter, metrics in mono) and using alignment and spacing as structural tools, the page can be visually compelling without requiring illustrations, photos, or complex visual assets -- which is important because this product has no UI screenshots or product imagery to show.

### Risks

**1. May feel too text-heavy for some users.** The direction is deliberately editorial and typography-driven. Users who scan rather than read may find the problem section (four text cards with no icons) and the differentiator section (pure text, no visual) sparse or boring. **Mitigation:** The scroll-driven entrance animations add motion that draws the eye to new content. The pipeline diagram in the solution section provides a strong visual anchor at the story's midpoint. The metric counter animation in the proof section adds visual interest. But this risk is real -- if the copy is not excellent, the direction has less visual decoration to compensate.

**2. Chapter transitions require careful scroll-distance tuning.** The chapter transition system depends on specific scroll distances (100px for divider draw, 150px for header entrance, etc.). These values need testing across viewport heights. On a tall viewport (1440px+), 100px of scroll is a small hand movement. On a short viewport (768px), 100px is more significant. If transitions feel too fast on large screens or too slow on small ones, the distance values need viewport-relative scaling. **Mitigation:** Test at 768px, 900px, 1080px, and 1440px viewport heights during implementation and adjust thresholds if needed.

**3. The single-column layout limits information density.** The 760px content column and single-column card stacking means the page will be physically longer than a bento-grid or two-column layout. Users who prefer to scan a dense feature grid may find the vertical length tedious. **Mitigation:** The chapter numbering and eyebrow labels provide scannability landmarks even in a long page. The features section does use a 2-column grid to compress that specific chapter. But the overall page length will be greater than Direction A or C.

**4. Left-aligned text may feel less "polished" than centered layouts to some audiences.** Centered text is the current norm for SaaS landing pages. The left-aligned editorial approach is deliberately different, but it could read as "unfinished" to users whose mental model of "professional landing page" is centered text on dark backgrounds. **Mitigation:** The hero IS centered, establishing professionalism. The shift to left-alignment for Chapter 01 onward should read as "editorial intent," not as "forgot to center." The chapter numbering system reinforces that the alignment is deliberate.

**5. No ambient motion in non-hero sections.** Unlike Direction A (which may use floating orbs or continuous glow animations), this direction has zero looping animations after the hero's scroll indicator fades out. Between scroll-triggered entrance animations, the page is completely still. This could feel "dead" to users who expect constant subtle motion on modern landing pages. **Mitigation:** The scroll-triggered animations fire frequently enough (every ~300-500px of scrolling) that the page never goes long without visual activity. The card hover states provide on-demand motion. But if the user stops scrolling mid-section, nothing moves. This is intentional (motion budget) but could feel static to some.

**6. The pipeline diagram is the direction's single complex visual element.** If its SVG/CSS implementation is not polished (clean line rendering, precise gate positioning, smooth track-draw animation), the page's visual credibility collapses at the most important moment. **Mitigation:** Build and test the pipeline diagram as a standalone component before integrating it into the page. Ensure the gradient track line renders cleanly at 2px width across browsers (subpixel rendering can make thin gradient lines look muddy on some displays -- use `shape-rendering: geometricPrecision` on the SVG or ensure the CSS gradient is applied to a properly anti-aliased element).
