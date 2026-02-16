# Visual Direction A: High-Tech Immersion

## 1. Direction Summary

A dark, atmospheric command-center aesthetic where the page feels like looking into a live system monitor. Deep navy-black backgrounds are punctuated by precise violet and cyan glow accents that trace the quality pipeline like illuminated circuitry. The mood is controlled confidence: this is not flashy sci-fi, it is the calm interior of a machine that knows what it is doing. Typography is clean and engineering-grade, glow is surgical rather than decorative, and every luminous element exists because it represents something the system is actually doing.

## 2. Visual Metaphor

**Mission control for code quality.** The user is looking at a monitoring dashboard for a system that runs without them. Think of the SpaceX launch control screens: dark backgrounds, data flowing through channels, status indicators glowing green when stages complete, the operator's role reduced to watching and approving. The pipeline is a visible flow of work moving through illuminated checkpoints. Gates glow when active, dim when dormant. Code enters as raw material on the left (violet) and emerges verified on the right (cyan). The user does not build -- they observe a system that builds, verifies, and reports.

---

## 3. Color System

### Background treatment

The page background is `#0a0b10` -- a blue-black that sits between pure black and navy. It is dark enough to make glow effects register but warm enough (via the blue undertone) to avoid the sterile, lifeless quality of `#000000`. This is the color of a turned-off monitor in a dark room: not void, but deep.

Alternating sections shift to `#0f1018`, which is 5 lightness points higher. This difference alone is nearly invisible on most screens, so alternating sections also receive a 1px horizontal gradient divider line at their top edge (fading from transparent at the edges to `rgba(255,255,255,0.10)` at center, 60% of the container width). This divider is the primary section separator, not the background shift.

The hero section has an additional atmospheric layer: three large blurred radial gradients (600px, 450px, 500px diameter) positioned at 20%/30%, 80%/60%, and 50%/80% of the section. These use `rgba(124,92,252,0.12)`, `rgba(0,212,255,0.06)`, and `rgba(90,61,232,0.08)` respectively, each with `filter: blur(80px)`. They drift slowly (8-second alternating loop, 30px translate range). This creates a mesh-gradient atmosphere behind the hero content -- a "lit from within" effect as if the system behind the page is powered on.

The final CTA section re-introduces this atmospheric glow treatment at reduced intensity (opacity multiplied by 0.6) to bookend the page. All middle sections use flat backgrounds with divider lines only.

### Surface hierarchy

Four surface levels, each progressively lighter:

| Level | Color | Use |
|-------|-------|-----|
| Canvas | `#0a0b10` | Page background |
| Recessed | `#0f1018` | Alternating section backgrounds |
| Card | `#14151f` | Resting cards, containers |
| Elevated | `#1a1b28` | Hovered cards, active states |
| Floating | `#212333` | Tooltips, popovers, modals |

Cards are distinguished from their backgrounds by a `1px solid rgba(255,255,255,0.06)` border. On hover, this border shifts to `rgba(124,92,252,0.40)` (violet-tinted) and the card background lifts one level. The border color change is the primary hover signal; the background shift is secondary reinforcement.

### Accent usage

The accent system uses a violet-to-cyan axis. Violet (`#7c5cfc`) is the brand identity color. Cyan (`#00d4ff`) is the "verified/passed" color. Green (`#34d399`) is the "success" color used only for checkmarks and passed indicators.

**What glows:**
- CTA buttons: Permanent subtle violet glow halo (`box-shadow: 0 0 20px rgba(124,92,252,0.45), 0 0 60px rgba(124,92,252,0.20)`). On hover, intensity increases to 0.65/0.30. Only the hero CTA and final CTA pulse (2.5s loop, opacity oscillating between 0.3 and 0.6). All other CTA buttons have static glow.
- Active pipeline gates: Cyan glow halo (`box-shadow: 0 0 20px rgba(0,212,255,0.60), 0 0 60px rgba(0,212,255,0.25)`). Only the currently-active gate glows at this intensity. Passed gates glow at half intensity. Inactive gates have no glow.
- Pipeline flow dots: Small (6px) circles that travel along the pipeline track. Each dot has `box-shadow: 0 0 10px rgba(167,139,250,0.50)`.
- Success checkmarks: Brief green glow (`box-shadow: 0 0 12px rgba(52,211,153,0.40)`) that appears on the 400ms spring-scale entrance animation and then fades to 50% intensity over 300ms.

**What does not glow:**
- Navigation elements (clean, functional, no glow)
- Body text (high-contrast white-on-dark, no effects)
- Feature cards at rest (glow only on hover, and only the border, not a halo)
- Pricing cards (subtle border treatment only, no halo)
- FAQ accordion items (purely functional)
- Section headlines (no text-shadow, no glow -- legibility first)

**Exception -- hero headline accent word:** The word "right" in "Who checks if it's right?" uses the violet-to-cyan gradient as `background-clip: text`. It also receives a very subtle text-shadow: `0 0 40px rgba(124,92,252,0.30), 0 0 80px rgba(124,92,252,0.10)`. This text-shadow creates a soft halo behind the gradient word, making it feel like a light source. This is the only text element with a glow effect on the entire page.

### Gradient strategy

Gradients appear in five specific places, never arbitrarily:

1. **Hero atmospheric mesh** (described above): Three blurred radial gradients creating ambient depth. Low opacity (0.06-0.12). Purpose: atmosphere, not decoration.

2. **Brand identity gradient** (`linear-gradient(135deg, #7c5cfc 0%, #00d4ff 100%)`): Applied as `background-clip: text` on three elements only: the nav logo text, the hero headline accent word, and the footer brand text. This gradient IS the brand mark. It represents the pipeline journey from raw (violet) to verified (cyan).

3. **Pipeline track gradient** (`linear-gradient(90deg, #7c5cfc 0%, #a78bfa 33%, #38bdf8 66%, #00d4ff 100%)`): Applied as a 2px top-border on the horizontal pipeline track in the hero and solution sections. This four-stop gradient shows the progression through all quality stages.

4. **Card diagonal shine** (`linear-gradient(135deg, rgba(255,255,255,0.04) 0%, transparent 50%)`): Applied as a `::before` pseudo-element on cards, visible only on hover (opacity transitions from 0 to 1 over 250ms). This mimics a light reflection passing over the card surface. Opacity is capped at 0.04 -- barely perceptible, but enough to add dimensionality.

5. **Section divider lines** (`linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.10) 20%, rgba(255,255,255,0.10) 80%, transparent 100%)`): 1px horizontal lines at the top of alternating sections. Purpose: structural separation.

Gradients never appear on large surface fills (no gradient backgrounds on sections, no gradient cards). They are always edge treatments, text treatments, or atmospheric layers.

### Ambient treatment

**Grain overlay:** A full-viewport fixed overlay using an SVG `feTurbulence` filter (`baseFrequency: 0.65`, `numOctaves: 3`, monochrome). Opacity: `0.035`. Blend mode: `overlay`. Pointer events: `none`. Z-index: `9999` (above everything). This grain adds tactile warmth to the dark surfaces -- the difference between looking at a screen and looking at a photograph of a screen. It reduces the "flat digital" quality without being consciously noticeable. Users should feel it, not see it.

**No other textures.** No paper, no fabric, no halftone. The grain is the single textural treatment. The atmosphere comes from color and light, not surface simulation.

---

## 4. Typography System

### Font choices

**Display and body: Inter** (variable font, optical sizing enabled via `opsz` axis)

Inter is chosen for three reasons specific to this direction:
1. Its geometric construction matches the precision/engineering mood. The letterforms are mathematically regular without being cold (unlike Roboto's mechanical feeling).
2. Its variable font optical sizing axis automatically adjusts stroke contrast and spacing based on rendered size, meaning the 72px hero headline and the 16px body text are both optimally readable from a single font load.
3. It is the de facto standard for developer tools (Linear, Vercel, Supabase). For the vibe coder audience, who likely uses these tools, Inter signals "this is a serious tool" without requiring them to articulate why.

Weights loaded: 400 (Regular), 500 (Medium), 600 (Semibold), 700 (Bold). No other weights.

**Monospace accent: JetBrains Mono** (weights 400 and 500 only)

JetBrains Mono appears in five specific contexts:
1. Pipeline gate labels ("BUILD", "ORGANIZE", "POLISH") -- signals these are system-defined stages, not marketing copy.
2. Metric numbers in social proof (e.g., "723" in "723 tests passing") -- signals these are real, measured values.
3. Inline code references if any spec snippet is shown (e.g., `spec.md`).
4. The pricing price values ("$0", "$15", "TBD") -- signals these are data points, not prose.
5. Eyebrow category labels above section headlines (e.g., "THE PROBLEM", "HOW IT WORKS") -- in JetBrains Mono at 12px, semibold, `letter-spacing: 0.08em`, uppercase. This creates a "system label" feeling, as if the page itself is a structured interface.

JetBrains Mono is never used for body text, headlines, descriptions, or button labels. It marks "system voice" vs. "human voice."

### Hierarchy through size, weight, spacing, and color

| Element | Size | Weight | Line height | Letter spacing | Color | Notes |
|---------|------|--------|-------------|---------------|-------|-------|
| Hero headline | `clamp(3rem, 5vw + 1rem, 4.5rem)` | 700 | 1.1 | -0.03em | `#edeef2` | Tighter tracking pulls the large text into a dense, confident block |
| Hero subhead | 1.125rem (18px) | 400 | 1.5 | 0em | `#9496a8` | Secondary color reduces visual weight below headline |
| Eyebrow labels | 0.75rem (12px) | 600, JetBrains Mono | 1.5 | 0.08em | `#7c5cfc` | Accent color + wide tracking + mono = "system category tag" |
| Section headlines | `clamp(2.25rem, 3vw + 0.75rem, 3rem)` | 700 | 1.25 | -0.02em | `#edeef2` | Same visual language as hero but smaller scale |
| Card titles | `clamp(1.25rem, 1.5vw + 0.25rem, 1.5rem)` | 600 | 1.25 | 0em | `#edeef2` | Semibold (not bold) -- subordinate to section headlines |
| Body copy | 1rem (16px) | 400 | 1.625 | 0em | `#9496a8` | Relaxed line height for comfortable reading. Secondary color keeps body text visually quieter than headlines |
| Button labels | 0.875rem (14px) | 600 | 1.5 | 0.04em | `#ffffff` | Wide tracking gives a "stamped" quality -- small, precise, deliberate |
| Captions/metadata | 0.75rem (12px) | 500 | 1.5 | 0.04em | `#5c5e72` | Muted color + small size = unobtrusive metadata |
| Pipeline gate labels | 0.75rem (12px) | 500, JetBrains Mono | 1.5 | 0.08em | `#00d4ff` (active) / `#5c5e72` (inactive) | Cyan on active gates, muted on inactive |

### How type creates the "feel"

The combination of tight-tracked bold headlines + relaxed-spaced body text creates a rhythm of **density then breath**. Headlines compress inward (negative tracking), body text opens outward (generous line height). This alternation mimics the feeling of a control panel: dense labels on instruments, then clean readout spaces between them.

The Inter + JetBrains Mono pairing creates a two-voice system: the "marketing voice" (Inter, proportional, warm) and the "system voice" (JetBrains Mono, monospaced, technical). When the page says "Your AI writes the code" it uses Inter. When it says "BUILD" on a pipeline gate label, it uses JetBrains Mono. The user instinctively understands: Inter = for you. Mono = the system speaking.

---

## 5. Shape and Composition

### Dominant shape primitives

**Primary: Rounded rectangles** with `border-radius: 16px` on cards and `10px` on buttons/inputs. This creates a modern, approachable feel that prevents the dark theme from feeling harsh or brutalist. The rounded corners soften the geometry without making it playful.

**Secondary: Circles** used exclusively for pipeline elements (gate icons are 48px circles, flow dots are 6px circles, status indicators are 8px circles). Circles represent nodes and checkpoints in the pipeline metaphor. They are functional, not decorative.

No irregular blobs, no sharp rectangles, no triangles. The shape vocabulary is deliberately limited to these two primitives to maintain visual consistency across the page.

### Card treatment

All cards share this base structure:
- Background: `#14151f`
- Border: `1px solid rgba(255,255,255,0.06)`
- Border radius: `16px`
- Padding: `24px` internal
- Shadow: `0 1px 2px rgba(0,0,0,0.30), 0 1px 3px rgba(0,0,0,0.15)` (barely visible, just enough to separate from background)

Interactive cards (bento, pricing) add on hover:
- Background shifts to `#1a1b28`
- Border shifts to `rgba(124,92,252,0.40)` (violet tint)
- Shadow deepens: `0 10px 25px rgba(0,0,0,0.35), 0 4px 10px rgba(0,0,0,0.20)`
- Diagonal shine pseudo-element fades in (`opacity: 0 to 1`, 250ms)
- Card glow halo: `0 0 30px rgba(124,92,252,0.20)` behind the card

Pipeline cards have an additional state:
- Active: `border-color: #7c5cfc`, cyan glow halo
- Passed: `border-color: rgba(0,212,255,0.30)`, green checkmark with glow

Glass cards (used only for pricing on gradient backgrounds):
- Background: `rgba(20,21,31,0.60)`
- Backdrop filter: `blur(20px)`
- Border: `1px solid rgba(255,255,255,0.10)`
- Border radius: `24px` (larger than standard cards to signal prominence)

### Section layout patterns

The page uses three layout patterns, not one repeated pattern:

**Pattern 1: Centered editorial** (Hero, Differentiator, Final CTA)
- Content centered, max-width 800px
- Headline + subhead + CTA stacked vertically
- Generous vertical padding (128px top, 96px bottom on hero; 96px both on others)
- Used for single-message sections that require no grid

**Pattern 2: Card grid** (Problem, Features, Pricing)
- Centered eyebrow + headline above the grid
- Grid below: 2 columns for problem cards, 6-column bento for features, 3 columns for pricing
- Cards staggered on scroll entry (80ms between each)

**Pattern 3: Directional flow** (Solution, How It Works)
- Content flows left-to-right (desktop) or top-to-bottom (mobile)
- Three stages/steps connected by a visual track (line or arrow)
- Each stage has an icon, label, and description
- The track uses the pipeline gradient (violet-to-cyan) as a 2px top/left border

These three patterns alternate across the page, preventing visual monotony while maintaining a cohesive system.

### Visual rhythm and whitespace

Vertical spacing follows a deliberate rhythm:

- Between page sections: `96px` (6rem). This is wide enough to feel like a chapter break.
- Between a section headline and its content: `48px` (3rem). Enough separation that the headline "floats" above the content block.
- Between cards in a grid: `32px` (2rem). Tight enough to read as a group, loose enough to scan individually.
- Inside a card, between title and description: `12px` (0.75rem). Snug -- title and description are a single unit.
- Inside a card, padding: `24px` (1.5rem) on all sides. Comfortable internal space.

Horizontal content width: `1200px` max for most sections, `800px` for text-heavy sections (problem, FAQ, differentiator, CTA), `1400px` for the bento grid. All sections have `16px` horizontal padding on mobile, scaling to `32px` on tablet and desktop.

### Bento grid approach

The feature grid uses a 6-column system at desktop where cards span either 2 or 3 columns:

```
Row 1: [  Card 1 (span 3)  ] [  Card 2 (span 3)  ]
Row 2: [ Card 3 (2) ] [ Card 4 (2) ] [ Card 5 (2) ]
Row 3: [        Card 6 (span 6, full width)        ]
```

This creates visual variety: the first row has two large cards (the two most important features), the second row has three equal cards, and the final card stretches full-width as a closing statement feature (e.g., "Your process, your rules").

At tablet (below 1024px): 4-column grid, cards span 2 each, producing 2 cards per row.
At mobile (below 640px): single column, all cards full-width, stacked vertically.

Cards within the bento grid are uniform height per row (CSS Grid handles this via `align-items: stretch`), but the content inside is top-aligned (cards with less text will have whitespace at the bottom rather than centered content).

---

## 6. Motion System

### The ONE "wow" in skin

**Animated mesh-gradient atmosphere in the hero.** Three large blurred color orbs drift slowly behind the hero content on 8-second alternating loops. The movement is glacial -- 30px of translation and 5% scale change per cycle. The orbs overlap and blend, creating a slowly shifting color field that suggests a living system behind the interface. This is the only ambient visual effect that modifies the page's appearance. It is confined to the hero section and the final CTA section (at 60% opacity). No other section has animated atmospheric effects.

The orbs are GPU-composited (using `transform` and `opacity` only, no layout recalculation) and run as CSS animations (no JavaScript). On reduced-motion preference, they stop immediately (animation-duration set to 0.01ms, iteration-count to 1).

### The ONE "wow" in behavior

**Sequential pipeline gate illumination on scroll.** When the hero pipeline visual enters the viewport, the three gates illuminate one at a time with a 300ms delay between each. Each gate:
1. Border transitions from `rgba(255,255,255,0.06)` to `#7c5cfc` (200ms, ease-standard)
2. Glow halo fades in (cyan, 0 to full intensity, 400ms, ease-decel)
3. Gate icon scales from `0.9` to `1.0` (400ms, ease-spring -- slight overshoot)
4. Checkmark pops in (scale 0 to 1, 400ms, ease-spring) after the gate glow reaches full intensity

The flow dots (6px circles) begin traveling along the pipeline track after the first gate illuminates. They move at a constant speed (3-second loop, linear easing), traveling left-to-right along the track and fading out at the right edge. Three dots are spaced evenly along the track, creating continuous flow.

This sequential illumination happens only once (Intersection Observer fires, then disconnects). If the user scrolls away and back, the gates remain illuminated. This is a reveal, not a loop.

### Scroll animation strategy

All scroll-triggered animations use the Intersection Observer API with a threshold of `0.15` (element 15% visible triggers the animation). No scroll event listeners, no JavaScript animation loops.

| Element | Transform start | Transform end | Duration | Easing | Stagger |
|---------|----------------|---------------|----------|--------|---------|
| Section headline | `translateY(24px), opacity: 0` | `translateY(0), opacity: 1` | 600ms | ease-decel | None |
| Body text | `translateY(16px), opacity: 0` | `translateY(0), opacity: 1` | 400ms | ease-decel | 80ms after headline |
| Problem cards | `translateX(-48px), opacity: 0` | `translateX(0), opacity: 1` | 400ms | ease-decel | 80ms between cards |
| Solution layer cards | `translateY(32px), opacity: 0, scale(0.97)` | `translateY(0), opacity: 1, scale(1)` | 600ms | ease-decel | 200ms between layers |
| Bento cards | `translateY(32px), opacity: 0, scale(0.97)` | `translateY(0), opacity: 1, scale(1)` | 600ms | ease-decel | 80ms between cards, max 6 in a stagger group |
| Pipeline gates | See "wow in behavior" above | | | | 300ms between gates |
| Pricing cards | `translateY(24px), opacity: 0` | `translateY(0), opacity: 1` | 400ms | ease-decel | 120ms between cards |
| FAQ items | `opacity: 0` | `opacity: 1` | 400ms | ease-decel | No stagger (each item has its own observer) |

Problem cards use `translateX` (slide from left) instead of `translateY` (fade up). This is the only horizontal entrance animation on the page. It creates a "card being dealt" effect that differentiates the problem section from every other section.

### Ambient animation budget

| Element | Type | Duration | Loop? | Where visible |
|---------|------|----------|-------|---------------|
| Hero orbs (x3) | translate + scale | 8s | Yes, alternate | Hero only |
| Pipeline flow dots (x3) | translateX along path | 3s | Yes | Hero pipeline only |
| Hero CTA glow pulse | box-shadow opacity | 2.5s | Yes | Hero CTA only |
| Final CTA glow pulse | box-shadow opacity | 2.5s | Yes | Final CTA only |
| Final CTA orbs (x3) | translate + scale | 8s | Yes, alternate | Final CTA only |

**Total looping animations:** 10 (7 in hero, 0 in middle sections, 3 in final CTA). At any scroll position, the maximum number of simultaneously visible looping animations is 7 (in the hero viewport). All middle sections have zero looping animations -- only one-shot entrance animations that fire and complete.

The nav CTA does not pulse. Pricing CTAs do not pulse. Only the two "anchor" CTAs (hero and final) pulse.

### Stagger and timing patterns

Stagger delay: `80ms` between items in a group. This is fast enough that the group reads as "appearing together with a wave" rather than "appearing one by one." At 80ms, a group of 6 items takes 400ms to fully appear, which fits within a single comfortable viewing moment.

Maximum stagger group: 6 items. If more than 6 items need to animate in, they all animate together (no stagger). This prevents the "popcorn" effect where animation becomes the focus instead of the content.

Spring easing is reserved for exactly two element types: pipeline gate icon scale-in and CTA button press (active state). Everything else uses decelerate easing for entries or standard easing for hover transitions. The spring easing (`cubic-bezier(0.34, 1.56, 0.64, 1.0)`) has an overshoot of approximately 6%, which reads as "snappy" without bouncing.

---

## 7. Section-by-Section Visual Treatment

### Section 1: Hero

**Background:** `#0a0b10` base with three blurred mesh-gradient orbs (violet at upper-left, cyan at lower-right, deep violet at bottom-center). The orbs create a warm, atmospheric glow that suggests depth. A `radial-gradient(ellipse 80% 50% at 50% 40%, rgba(124,92,252,0.12) 0%, rgba(0,212,255,0.04) 40%, transparent 70%)` is layered beneath the orbs as a stable base glow. Grain overlay covers everything.

**Layout:** Centered column, max-width 900px. Content stacks: eyebrow label ("AI-POWERED CODE QUALITY", JetBrains Mono, 12px, violet) > headline (48-72px, bold, white) > subhead (18px, regular, secondary gray) > CTA group (primary button + secondary ghost button, side by side on desktop, stacked on mobile) > friction reducer text (12px, muted) > pipeline visual (below, 96px margin-top).

The hero has `min-height: 100vh` but the pipeline visual pushes below the fold on most viewports. A scroll indicator (a thin 24px chevron icon in muted color, with a 2-second bounce animation, 8px travel) sits at the absolute bottom of the hero viewport, 32px from the bottom edge. This prevents the "illusion of completeness."

**Pipeline visual:** A horizontal track (2px line using the 4-stop pipeline gradient) connects three gate nodes. Each gate is a 48px circle (JetBrains Mono label below: "BUILD", "ORGANIZE", "POLISH") with a check icon inside. Flow dots (6px, glowing) travel along the track. The pipeline is centered within the max-width container. On mobile (below 640px), it switches to vertical orientation (track becomes a left-side line, gates stack vertically).

**Animation:** Orbs drift continuously. On viewport entry, headline fades up (24px, 600ms), subhead fades up (16px, 400ms, 80ms delay), CTAs fade up (16px, 400ms, 160ms delay), pipeline gates illuminate sequentially (300ms stagger, see motion system above). Scroll indicator bounces continuously (2s loop).

**Transition to next section:** A 1px gradient divider line appears at the bottom of the hero where the problem section begins. The hero's atmospheric orbs fade naturally at the edges (blur handles this), so the transition from atmospheric hero to flat problem section feels like stepping out of the glow into clean reading space.

### Section 2: Problem ("The truth about AI coding")

**Background:** `#0f1018` (secondary background). 1px gradient divider at top edge. No atmospheric effects -- this section is deliberately stark compared to the hero. The contrast in visual treatment mirrors the narrative: the hero promises capability, the problem section shows raw pain.

**Layout:** Centered eyebrow + headline (max-width 800px), then a 2-column card grid (max-width 1000px) below. Two cards per row on desktop, single column on mobile. Cards are evenly sized.

**Key visual elements:** Each problem card has a left-side icon (24px, line-style SVG, colored in `--error` red `#f87171` for the first three cards, and `--warning` yellow `#fbbf24` for the fourth "Nobody checks" card). The icon color signals severity. Card titles are white, descriptions are secondary gray.

**Animation:** Eyebrow fades in, then headline (80ms later), then cards slide in from left (`translateX(-48px)`, 80ms stagger between the four cards). The left-slide is unique to this section. Each card enters as if being dealt from a deck, creating a "revelation" rhythm that matches the narrative (each card reveals a new pain point).

**Transition to next:** 1px gradient divider at bottom. The section ends with generous whitespace (96px padding-bottom) before the solution section begins.

### Section 3: Solution ("A team of AI specialists, working for you")

**Background:** `#0a0b10` (primary background). No divider at top (the previous section's bottom divider handles separation). A very subtle `radial-gradient(circle at 50% 50%, rgba(124,92,252,0.04) 0%, transparent 60%)` is applied as a background layer -- barely visible, but adds a whisper of warmth at the center of the section.

**Layout:** Centered eyebrow + headline + intro paragraph (max-width 800px), then three horizontally-connected layer cards below (max-width 1200px). The three cards represent Build, Organize, and Polish. On desktop, they sit in a row connected by a horizontal pipeline track (the same 2px gradient line from the hero). On mobile, they stack vertically with a vertical track on the left.

**Key visual elements:** Each layer card has:
- A top-left layer badge ("L1", "L2", "L3" in JetBrains Mono, 11px, inside a 28px rounded pill, background `rgba(124,92,252,0.15)`, text in violet)
- A title (e.g., "Build", "Organize", "Polish") in 20-24px semibold
- A description in secondary gray
- The connecting pipeline track between cards glows at the segment closest to the "active" card (the one most recently scrolled into view)

The key insight callout ("You describe what you want. The system handles quality control.") appears below the three cards as a standalone centered text block, styled as a pull quote: 18px, medium weight, violet color, with a left border of 2px solid violet.

**Animation:** Cards fade up with scale (`translateY(32px), scale(0.97)`, 600ms, ease-decel) with 200ms stagger between the three layers. The 200ms stagger (longer than the standard 80ms) creates a "one, then another, then another" rhythm that reinforces the layered pipeline concept. Each card's border transitions to a subtle cyan tint when `is-visible` is applied, suggesting the gate has activated.

**Transition to next:** 96px padding-bottom, then a 1px divider before the how-it-works section.

### Section 4: How It Works (simplified 3-step)

**Background:** `#0f1018` (secondary). 1px divider at top.

**Layout:** Centered eyebrow + headline (max-width 800px). Then three step blocks arranged horizontally on desktop (max-width 1200px), vertically on mobile. Each step is a card with a large circled number (48px circle, border `1px solid rgba(124,92,252,0.40)`, number in JetBrains Mono 20px bold, violet color), a title, and a description. Steps are connected by dashed horizontal lines (2px dashed `rgba(255,255,255,0.10)`) between the circled numbers, suggesting sequence without the formality of the pipeline track.

**Key visual elements:** The circled step numbers are the visual anchor of this section. They are intentionally larger and more prominent than any other numeric element on the page. The dashed connecting line (not solid) differentiates this section's visual language from the pipeline visual in the hero/solution sections -- these are user steps, not system stages.

**Animation:** Headline fades up, then steps fade up with 80ms stagger. The step numbers have a brief scale-spring on entry (from 0.9 to 1.0, 400ms, ease-spring) that gives them a slight "pop" as they appear.

**Transition to next:** 96px padding-bottom, divider.

### Section 5: Social Proof + Features

This section is split into two sub-sections with no divider between them (they read as a single unit).

**Sub-section 5a: Social Proof Strip**

**Background:** `#0a0b10` (primary).

**Layout:** A single horizontal strip (max-width 1200px), centered, containing 3-4 proof badges arranged as inline-flex items with 48px gaps between them. Each badge is a compact unit: an icon or number + a label. Examples:
- A checkmark icon + "723 Tests Passing" (number in JetBrains Mono, bold, cyan; label in Inter, regular, secondary gray)
- A shield icon + "52/52 Requirements Tracked" (same style)
- Integration logos: Claude, GPT, Cursor, Windsurf icons (24px, monochrome white at 60% opacity)

The strip has no background card -- it sits directly on the section background. A `1px solid rgba(255,255,255,0.06)` top and bottom border frames it as a data bar.

On mobile, the strip wraps to 2 columns (2x2 grid of badges).

**Animation:** The entire strip fades in as a single unit (no stagger, 400ms, ease-decel).

**Sub-section 5b: Feature Bento Grid**

**Background:** Same `#0a0b10`, continuous from the proof strip.

**Layout:** Centered eyebrow + headline above the grid. The 6-column bento grid (max-width 1400px) as described in the composition section. Cards contain: a 32px icon (line-style SVG, violet color), a title (20-24px, semibold), and a description (16px, secondary gray).

Each card has the standard card treatment (border, radius, shadow). On hover: border goes violet, diagonal shine appears, subtle glow halo. The icon in each card is the only colored element at rest (violet). Title and description are white and gray respectively.

**Key visual elements:** The bento grid's visual interest comes from the size variation (3-col and 2-col cards in different rows) rather than color variation. All cards use the same colors; hierarchy comes from size.

**Animation:** Cards fade up with scale (600ms, ease-decel, 80ms stagger, max 6 per group). The two-column stagger means row 1's two cards appear nearly simultaneously (80ms apart), row 2's three cards cascade across 160ms, creating a "wave" that moves down and across the grid.

**Transition to next:** 96px padding, divider.

### Section 6: Differentiator ("Not another AI code generator")

**Background:** `#0f1018` (secondary). 1px divider at top.

**Layout:** Centered editorial column, max-width 800px. No grid, no cards. This section is purely typographic. The structure is: eyebrow + headline + three comparison statements + body paragraph.

The three comparison statements ("They build. We build AND verify." etc.) are styled as a stacked list with generous vertical spacing (24px between each). Each statement uses a two-part structure: the "They" clause in secondary gray, the "We" clause in white with the key differentiating word (e.g., "verify", "check", "confidence") in the violet-to-cyan gradient text. This creates a visual rhythm of gray-then-bright, gray-then-bright that draws the eye to the differentiating words.

**Key visual elements:** No icons, no cards, no graphics. The typography IS the visual. The gradient-clipped differentiating words are the only color accents. This restraint makes the section feel like an editorial statement, not a feature list.

**Animation:** Headline fades up, then each comparison statement fades up individually (400ms, ease-decel, 120ms stagger). The stagger is slightly longer than card stagger because these are meant to be read sequentially -- each one lands and is absorbed before the next appears.

**Transition to next:** 96px padding, divider.

### Section 7: Pricing

**Background:** `#0a0b10` (primary). A subtle `radial-gradient(circle at 50% 30%, rgba(124,92,252,0.06) 0%, transparent 50%)` is applied behind the pricing cards, creating a faint spotlight effect that draws attention to the pricing area without being obtrusive.

**Layout:** Centered eyebrow + headline (max-width 800px). Then three pricing cards in a row (max-width 1000px, equal width). On mobile, cards stack vertically. The middle card ("Hybrid $15/mo") has a "Popular" badge (pill shape, background `rgba(124,92,252,0.20)`, text in violet, JetBrains Mono, 11px) and a slightly thicker border (1.5px instead of 1px) to indicate recommendation.

**Key visual elements:** Pricing values ("$0", "$15", "TBD") are rendered in JetBrains Mono at 36-48px (using `--text-h1` scale, not `--text-hero` -- these are card-sized, not page-sized). Weight: bold. Color: white. The "Free" label below the $0 is in success green. Feature lists use check icons in success green and small secondary-gray text.

A CTA button appears below the pricing grid (centered, primary style), not inside each card. This avoids three competing buttons and funnels all pricing-section conversions to a single action.

**Animation:** Headline fades up. Pricing cards fade up with 120ms stagger (slightly slower than bento cards because there are only 3 -- the slower stagger prevents the three-card appearance from feeling instantaneous).

**Transition to next:** 96px padding, divider.

### Section 8: FAQ

**Background:** `#0f1018` (secondary). 1px divider at top.

**Layout:** Centered editorial column, max-width 800px. Eyebrow + headline, then accordion items stacked vertically. Each accordion item is a `<details>` element with the question as `<summary>`.

**Key visual elements:** Accordion items have a top border of `1px solid rgba(255,255,255,0.06)` separating each one. The expand/collapse icon is a small chevron (12px, secondary gray) that rotates 180 degrees on open (200ms, ease-standard). Questions are 16px, semibold, white. Answers are 16px, regular, secondary gray, with 16px top-padding when expanded.

No cards here. The FAQ uses the simplest possible visual treatment: text on background, separated by hairline borders. This is intentional -- the FAQ is a utility section, not a showcase section. Visual restraint here prevents the late-page fatigue that occurs when every section demands visual attention.

**Animation:** Each FAQ item fades in with `opacity: 0 to 1` (400ms, ease-decel) on scroll. No stagger -- each item has its own observer because the user may scroll to individual questions. The accordion open/close is not animated beyond the chevron rotation (animating content height is technically complex for `<details>` and adds little value here).

**Transition to next:** 96px padding. No divider before the final CTA -- instead, the final CTA section's atmospheric glow creates its own visual break.

### Section 9: Final CTA

**Background:** `#0a0b10` base with the atmospheric mesh-gradient treatment re-introduced at 60% of the hero's intensity. Two blurred orbs (violet and cyan, 400px diameter, `filter: blur(80px)`, opacity 0.07 and 0.04) drift slowly behind the content. A `radial-gradient(ellipse 80% 50% at 50% 40%, rgba(124,92,252,0.08) 0%, rgba(0,212,255,0.03) 40%, transparent 70%)` provides a stable base glow.

This atmospheric return signals to the user: "you've completed the journey, you're back where you started, here's the action." The symmetry with the hero creates a narrative arc.

**Layout:** Centered editorial column, max-width 700px. Headline (echoing the hero promise, 36-48px), subhead (18px, secondary gray), email input + submit button (side by side on desktop, stacked on mobile), friction reducer text (12px, muted).

**Key visual elements:** The email input and button form a single visual unit: the input has a right-side border-radius of 0, the button has a left-side border-radius of 0, and they share a 1px border that makes them look like a single segmented control. The button has the pulsing CTA glow. The input has a focus state that adds a `box-shadow: 0 0 0 3px rgba(124,92,252,0.20)` ring.

Below the form: a success state. When the email is submitted, the form is replaced by a checkmark icon (scale-spring animation, 400ms) + "You're on the list!" message in success green + a secondary line in muted gray.

**Animation:** Headline and subhead fade up (standard). Form elements fade up with slight delay. The CTA button begins pulsing its glow immediately upon becoming visible. The orbs drift continuously.

**Transition to footer:** The atmospheric glow fades naturally at the bottom edge (the radial gradients terminate before the section edge). The footer sits on flat `#0a0b10` with a 1px divider.

### Footer

**Background:** `#0a0b10`, 1px divider at top.

**Layout:** Simple single-row on desktop: brand name (left, gradient text using the brand identity gradient) + copyright + link to privacy/terms (right). On mobile, stacked center-aligned.

No social media icons (no accounts to link). No sitemap (single-page site). No newsletter (the CTA section handles email capture). The footer is minimal -- its only job is legal compliance and brand closure.

---

## 8. Strengths and Risks

### Strengths

**Visual distinctiveness in the market.** No competitor in the AI coding space uses a violet-cyan accent palette on deep navy. Cursor is warm/beige, Windsurf is teal, Bolt is light, Devin is moody/dark without specific accent ownership. This direction creates immediate visual differentiation that a vibe coder would remember: "the one with the purple glow."

**Metaphor carries the product story.** The mission-control / pipeline-monitor metaphor is not decorative -- it directly explains how the product works. Gates that illuminate, flow dots that travel, checkmarks that appear: these are not abstract animations, they are literal representations of what the system does. A user who has only seen the hero pipeline visual already understands the core concept.

**Accessible complexity.** The page looks sophisticated (dark theme, glow, precision typography) but the information architecture is simple (9 sections, linear scroll, no navigation maze). This serves the vibe coder audience: they want to feel like they are using serious tooling without needing to understand complexity. The visual sophistication signals "this was built by people who know what they're doing" without requiring the user to know what they are doing.

**Performance-safe.** No heavy dependencies (no Three.js, no GSAP, no WebGL). All animations are CSS-based or use lightweight Intersection Observer JS. The mesh gradients are CSS radial gradients with blur, not rendered textures. The total JavaScript for animation behavior is under 100 lines. The page should achieve 90+ Lighthouse performance scores.

**Motion restraint despite the "high-tech" label.** The motion system is explicit about what moves and what does not. Middle sections have zero looping animations. The "wow" elements are concentrated in two bookend sections (hero and final CTA). This prevents the common failure mode of high-tech landing pages where everything pulses, glows, and floats until the user's eyes slide off the page.

### Risks

**Dark theme alienates some users.** Vibe coders who primarily use light-theme tools (v0, Replit's light mode, standard web apps) may find a dark page unfamiliar or harder to read. The secondary-gray body text (`#9496a8`) on dark backgrounds requires careful monitor calibration -- on washed-out laptop screens in bright environments, it may read as low-contrast. Mitigation: ensure `--text-secondary` passes WCAG AA at all sizes used, and consider a "the page looks best in a dimmed room" implicit understanding.

**Glow effects lose impact on light/dim screens.** The entire visual identity depends on glow being perceptible. On OLED screens with perfect blacks, the glows will look stunning. On cheap TN panels with poor contrast, or screens viewed in direct sunlight, the glow effects may be invisible or appear as flat colored shadows. Mitigation: the page must still work WITHOUT glow -- the information architecture, typography hierarchy, and layout are robust enough to carry the page even if every glow is invisible.

**"Cool but cold" perception.** The controlled, precise aesthetic could read as impersonal or intimidating to users who are not developers. The vibe coder audience is not the same as the infrastructure engineer audience. Some vibe coders may want warmth, friendliness, and approachability rather than command-center precision. Mitigation: the copy is warm and empathetic (it leads with feelings they recognize, not technical jargon). The visual direction creates contrast: cool visuals + warm words.

**No product screenshots.** This direction leans heavily on abstract visualization (pipeline diagrams, flow animations) because no product UI exists. For a vibe coder used to seeing product screenshots on landing pages, the absence of "what does the actual app look like?" may reduce credibility. Mitigation: the pipeline visual IS a product concept illustration, even if it is not a screenshot. The page should make it clear this is a preview/waitlist, not a launched product.

**Pipeline metaphor may over-promise complexity.** The three-layer pipeline visual is visually impressive but could make the product seem complicated to use. A vibe coder might think "I don't want to manage a pipeline." Mitigation: the "How it works" section exists specifically to collapse the complexity into "you describe, we build, you ship." The pipeline visual shows what the SYSTEM does; the how-it-works section shows what the USER does (which is almost nothing).

### Audience fit

This direction serves best:
- Vibe coders who have used dark-theme developer tools and find them aspirational (Cursor, VS Code dark, terminal aesthetics)
- Users who want to feel like they are using serious, professional-grade tooling
- Audiences who associate visual precision and glow aesthetics with quality and competence
- Users who are browsing in dim/dark environments (evening coding sessions, dark rooms)

This direction serves less well:
- Users who primarily work in bright environments with light-theme applications
- Audiences who associate dark themes with "for developers only" and feel excluded
- Users who want warmth, illustration, and personality over precision
- Audiences who are skeptical of visual polish without product substance
