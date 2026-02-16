# Visual Direction C: Editorial Clarity

**Date**: 2026-02-14
**Playbook base**: Playbook 1 (Bento clarity + subtle delight) + editorial typography emphasis
**Core thesis**: The page feels premium and trustworthy because of precision, not atmosphere. Clarity is the aesthetic. Information is the visual interest. Typography is the tool.

---

## 1. Direction Summary

This direction treats the landing page as an editorial artifact -- a precisely typeset document where every letter, every gap, and every rule is placed with intention. Visual interest comes from the contrast between oversized display type and tightly set body copy, from the rhythm of a bento grid whose card headlines read like newspaper section heads, and from the restrained use of a single violet accent against a near-monochrome palette. Where Direction A builds atmosphere with glows and Direction B tells a scroll-driven story, Direction C earns trust through typographic confidence: the kind of assured, quiet authority that says "we know exactly what we're doing" without needing to dazzle.

---

## 2. Visual Metaphor

**The published specification.**

The page reads like a beautifully typeset technical document -- a printed spec sheet or a well-designed annual report. Not cluttered. Not dry. But measured, precise, and confident. The visual metaphor is the published standard: the document that defines how things should be done. This mirrors the product itself -- Spec Manager is the authority that ensures code meets its specification. The page's own visual precision is the proof of that promise.

Secondary metaphor: the inspection report. Each bento card is a finding. Each section is a chapter. The reader is reviewing the evidence, not being sold to. Information architecture does the convincing.

---

## 3. Color System

### Competitive positioning

Direction C differentiates by pulling AWAY from the dark-mode consensus. While Cursor, Devin, Replit, and most devtools default to deep blacks, this direction uses a light-on-dark approach that is closer to an editorial layout: either a very light background (off-white) with dark text, OR a controlled dark background with dramatically higher contrast between surface layers than the existing tokens provide. The recommendation is a **dark base with strong surface contrast** -- dark enough to feel technical, light enough in its surfaces to feel editorial.

### Background treatment

```css
:root {
  /* Base: deep blue-black, slightly warmer than pure black.
     Same positioning as existing tokens but the key difference
     is HOW MUCH surface contrast exists above this. */
  --bg-primary: #0c0d14;

  /* Alternating section background: noticeably lighter than primary.
     The existing 5-point difference (#0a0b10 vs #0f1018) is imperceptible
     on most monitors. This direction increases it to a 12-point jump. */
  --bg-secondary: #13141e;

  /* Editorial "feature" background: used for ONE section (the how-it-works
     or differentiator) to break monotony. A warm off-black with the
     faintest blue undertone. */
  --bg-feature: #181a26;
}
```

### Surface hierarchy

The editorial approach demands VISIBLE surface layers. Cards must clearly lift off the background. The gap between background and surface must be wide enough to read as intentional whitespace framing, not subtle elevation.

```css
:root {
  /* Card surface: clearly lighter than background. 20+ points of
     lightness difference from --bg-primary, not the existing 10. */
  --surface-1: #1c1e2e;

  /* Elevated surface: hovered cards, active states.
     Another clear step up. */
  --surface-2: #252840;

  /* Highest elevation: tooltips, popovers, modal-like overlays. */
  --surface-3: #2e3150;
}
```

### Text hierarchy

```css
:root {
  /* Primary text: slightly warm white. NOT pure white (#fff)
     which causes halation on dark backgrounds. */
  --text-primary: #eef0f6;

  /* Secondary text: descriptions, supporting copy. High enough contrast
     to pass WCAG AA for body text (16px+) on --bg-primary. */
  --text-secondary: #9ea0b8;

  /* Muted text: captions, metadata, labels. Only used at 14px+ and
     for non-essential information. */
  --text-muted: #6b6d85;

  /* Display text: used ONLY for hero headline and one or two
     oversized section headlines. Pure white is acceptable here because
     display type at 48-72px does not suffer halation the way body text does. */
  --text-display: #ffffff;
}
```

### Accent usage

One accent color. Violet. Used surgically.

```css
:root {
  /* Core accent: same violet as existing tokens. Distinctive in the
     competitive landscape (no one owns violet). */
  --accent: #7c5cfc;

  /* Light variant: for hover states, interactive highlights. */
  --accent-light: #9b82fd;

  /* Dark variant: for pressed/active states. */
  --accent-dark: #5a3de8;

  /* Accent at text-safe contrast: a slightly lighter violet that
     passes WCAG AA at 16px on --bg-primary. Used for inline accent
     text, links, and small labels. */
  --accent-text: #a78bfa;
}
```

**Accent budget rule**: On any given screen, accent violet appears in a maximum of 3 elements: the CTA button, one typographic accent (headline word, eyebrow, or label), and one structural element (border, underline, or icon). If a fourth element needs accent, one of the first three must revert to neutral.

### Gradient strategy

Gradients are MINIMAL in this direction. No gradient backgrounds. No mesh gradients. No atmospheric glow orbs. The gradient is used in exactly two places:

1. **The CTA button** -- a subtle violet-to-slightly-lighter-violet gradient (not violet-to-cyan). The gradient should be barely perceptible, adding depth to the button without making it feel "designed."

```css
:root {
  --gradient-cta: linear-gradient(135deg, #7c5cfc 0%, #8b6ffd 100%);
}
```

2. **The pipeline visualization** -- a horizontal violet-to-cyan gradient along the pipeline track in the how-it-works section. This is the ONE place where the full brand gradient appears, and its appearance here reinforces the metaphor (code enters violet, exits verified cyan).

```css
:root {
  --gradient-pipeline: linear-gradient(90deg, #7c5cfc 0%, #00d4ff 100%);
}
```

No other gradients. No section divider gradients. No card shine gradients. The page is flat and proud of it.

### Ambient treatment

**None.** No glow orbs. No mesh backgrounds. No floating particles. No noise/grain overlay. The absence of atmosphere IS the aesthetic. The page breathes through whitespace, not through effects. This is the sharpest contrast with Direction A.

The only ambient element is the pipeline flow animation in the how-it-works section -- small dots traveling along the pipeline track. This is informational (it illustrates the concept), not decorative.

---

## 4. Typography System

This is the star of Direction C. Typography does 80% of the visual work.

### Font choices

**Display font: "Instrument Serif" (Google Fonts)**

A contemporary editorial serif with high contrast between thick and thin strokes, designed for display use at large sizes. It brings the "published document" feeling without being stuffy. The contrast between its elegant serifs and the geometric sans-serif body text creates the visual tension that makes the page interesting.

Why Instrument Serif:
- Free on Google Fonts (no licensing cost)
- Designed explicitly for display/headline use (not body text)
- High stroke contrast reads as premium and intentional at large sizes
- Pairs well with geometric sans-serifs
- Distinctive -- almost no devtool landing pages use serif display type, which makes this direction instantly recognizable

Load: `wght@400` only (it is a display font, used at 48px+ where regular weight reads as elegant, not light).

**Body font: "Inter" (Google Fonts)**

The existing choice is correct for this direction. Inter is the workhorse: geometric, highly legible, variable weight, optical sizing. It plays the neutral partner to Instrument Serif's character.

Why Inter stays:
- Excellent legibility at body sizes (16px)
- Variable font with optical sizing adapts to every size on the page
- Neutral enough to let the serif display type do the personality work
- Industry standard for devtools (familiar signal)

Load: `opsz,wght@14..32,400;500;600;700` (same as existing).

**Mono font: "JetBrains Mono" (Google Fonts)**

Used for code snippets, technical labels, metric numbers, and pipeline gate identifiers. In this direction, mono appears MORE frequently than in A or B because the editorial approach treats code-like text as a typographic texture -- a visual signal that says "this is precise."

Load: `wght@400;500` (same as existing).

### Google Fonts import

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif&family=Inter:opsz,wght@14..32,400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
```

### CSS font stacks

```css
:root {
  --font-display: 'Instrument Serif', 'Georgia', 'Times New Roman', serif;
  --font-body: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --font-mono: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Consolas', monospace;
}
```

### Type scale

Based on a 1.333 ratio (Perfect Fourth) starting from 16px base. This produces larger jumps between levels than the existing Major Third scale, which is intentional -- the editorial approach requires DRAMATIC size contrast between headlines and body text. The headline should feel enormous next to the body copy. That contrast is the visual interest.

```css
:root {
  /* ===== FONT SIZES ===== */

  /* Display hero: the single largest text on the page. Instrument Serif.
     At desktop, this renders at ~72px. At mobile, ~40px.
     This is ONLY for the hero headline. */
  --text-display: clamp(2.5rem, 5vw + 1.25rem, 4.5rem);
  /* 40px at 375px viewport, 72px at 1280px+ */

  /* Section headline: Instrument Serif. Large enough to command the
     section but clearly subordinate to the display size. */
  --text-h1: clamp(2rem, 3vw + 0.75rem, 3rem);
  /* 32px at 375px, 48px at 1280px+ */

  /* Subsection headline: Inter semibold. Used for solution layer
     titles, differentiator subheads. */
  --text-h2: clamp(1.5rem, 2vw + 0.5rem, 2rem);
  /* 24px at 375px, 32px at 1280px+ */

  /* Card title: Inter semibold. The "mini headline" inside each
     bento card. Must be scannable at a glance. */
  --text-h3: clamp(1.125rem, 1.25vw + 0.25rem, 1.375rem);
  /* 18px at 375px, 22px at 1280px+ */

  /* Eyebrow / label: Inter semibold, tracked wide. The small
     categorization text above headlines. */
  --text-eyebrow: 0.8125rem;
  /* 13px -- fixed, does not scale */

  /* Body large: for hero subhead and lead paragraphs. */
  --text-body-lg: 1.125rem;
  /* 18px */

  /* Body: standard reading text. */
  --text-body: 1rem;
  /* 16px */

  /* Small: secondary information, button labels. */
  --text-small: 0.875rem;
  /* 14px */

  /* Caption: metadata, fine print, mono labels. */
  --text-caption: 0.75rem;
  /* 12px */
}
```

### Font weights

```css
:root {
  --weight-regular: 400;
  --weight-medium: 500;
  --weight-semibold: 600;
  --weight-bold: 700;
}
```

### Line heights

```css
:root {
  /* Display headlines (Instrument Serif at 40-72px).
     Extremely tight -- the serifs need less interline space,
     and tight leading on large type is the editorial look. */
  --leading-display: 1.05;

  /* Section headlines (Instrument Serif at 32-48px). */
  --leading-heading: 1.15;

  /* Subsection and card headlines (Inter at 18-32px). */
  --leading-snug: 1.25;

  /* Body text. Comfortable reading. */
  --leading-body: 1.6;

  /* Body large (hero subhead, lead paragraphs). Slightly tighter
     than body because the larger size provides its own breathing room. */
  --leading-body-lg: 1.5;
}
```

### Letter spacing

```css
:root {
  /* Display headlines: pull in slightly. At 72px, default tracking
     on Instrument Serif is already generous. Negative tracking
     increases visual density and authority. */
  --tracking-display: -0.025em;

  /* Section headlines: same principle, lighter touch. */
  --tracking-heading: -0.02em;

  /* Body text: no adjustment. Inter's default metrics are well-calibrated. */
  --tracking-body: 0em;

  /* Eyebrows: tracked wide. This is the classic editorial device --
     small, semibold, widely tracked text above a headline signals
     "category" or "section." It is a visual pattern readers
     unconsciously recognize from magazines and newspapers. */
  --tracking-eyebrow: 0.1em;

  /* Mono text: slightly wider than default for readability at small sizes. */
  --tracking-mono: 0.02em;

  /* CTA buttons: wider tracking for authority and scan speed. */
  --tracking-cta: 0.06em;
}
```

### Complete typographic hierarchy

| Element | Font family | Size token | Weight | Line height | Letter spacing | Color | Text transform |
|---------|------------|-----------|--------|-------------|---------------|-------|---------------|
| Hero headline | `--font-display` (Instrument Serif) | `--text-display` (40-72px) | 400 | `--leading-display` (1.05) | `--tracking-display` (-0.025em) | `--text-display` (#fff) | None (sentence case) |
| Hero subhead | `--font-body` (Inter) | `--text-body-lg` (18px) | 400 | `--leading-body-lg` (1.5) | `--tracking-body` (0) | `--text-secondary` (#9ea0b8) | None |
| Eyebrow label | `--font-body` (Inter) | `--text-eyebrow` (13px) | 600 | 1.0 | `--tracking-eyebrow` (0.1em) | `--accent-text` (#a78bfa) | Uppercase |
| Section headline | `--font-display` (Instrument Serif) | `--text-h1` (32-48px) | 400 | `--leading-heading` (1.15) | `--tracking-heading` (-0.02em) | `--text-primary` (#eef0f6) | None (sentence case) |
| Section intro | `--font-body` (Inter) | `--text-body-lg` (18px) | 400 | `--leading-body-lg` (1.5) | `--tracking-body` (0) | `--text-secondary` (#9ea0b8) | None |
| Subsection head | `--font-body` (Inter) | `--text-h2` (24-32px) | 600 | `--leading-snug` (1.25) | `--tracking-body` (0) | `--text-primary` (#eef0f6) | None |
| Card title | `--font-body` (Inter) | `--text-h3` (18-22px) | 600 | `--leading-snug` (1.25) | `--tracking-body` (0) | `--text-primary` (#eef0f6) | None |
| Card body | `--font-body` (Inter) | `--text-body` (16px) | 400 | `--leading-body` (1.6) | `--tracking-body` (0) | `--text-secondary` (#9ea0b8) | None |
| Body copy | `--font-body` (Inter) | `--text-body` (16px) | 400 | `--leading-body` (1.6) | `--tracking-body` (0) | `--text-secondary` (#9ea0b8) | None |
| Metric number | `--font-mono` (JetBrains Mono) | `--text-h2` (24-32px) | 500 | `--leading-snug` (1.25) | `--tracking-mono` (0.02em) | `--text-primary` (#eef0f6) | None |
| Metric label | `--font-body` (Inter) | `--text-small` (14px) | 500 | `--leading-snug` (1.25) | `--tracking-body` (0) | `--text-muted` (#6b6d85) | None |
| Pipeline gate label | `--font-mono` (JetBrains Mono) | `--text-caption` (12px) | 500 | 1.0 | `--tracking-mono` (0.02em) | `--accent-text` (#a78bfa) | Uppercase |
| CTA button | `--font-body` (Inter) | `--text-small` (14px) | 600 | 1.0 | `--tracking-cta` (0.06em) | #ffffff | Uppercase |
| Secondary button | `--font-body` (Inter) | `--text-small` (14px) | 600 | 1.0 | `--tracking-cta` (0.06em) | `--text-primary` (#eef0f6) | Uppercase |
| FAQ question | `--font-body` (Inter) | `--text-h3` (18-22px) | 600 | `--leading-snug` (1.25) | `--tracking-body` (0) | `--text-primary` (#eef0f6) | None |
| FAQ answer | `--font-body` (Inter) | `--text-body` (16px) | 400 | `--leading-body` (1.6) | `--tracking-body` (0) | `--text-secondary` (#9ea0b8) | None |
| Nav links | `--font-body` (Inter) | `--text-small` (14px) | 500 | 1.0 | `--tracking-body` (0) | `--text-secondary` (#9ea0b8) | None |
| Pricing price | `--font-display` (Instrument Serif) | `--text-h1` (32-48px) | 400 | `--leading-heading` (1.15) | `--tracking-heading` (-0.02em) | `--text-primary` (#eef0f6) | None |
| Pricing tier name | `--font-body` (Inter) | `--text-eyebrow` (13px) | 600 | 1.0 | `--tracking-eyebrow` (0.1em) | `--accent-text` (#a78bfa) | Uppercase |
| Pricing feature line | `--font-body` (Inter) | `--text-small` (14px) | 400 | `--leading-body` (1.6) | `--tracking-body` (0) | `--text-secondary` (#9ea0b8) | None |
| Inline code | `--font-mono` (JetBrains Mono) | `--text-small` (14px) | 400 | inherit | `--tracking-mono` (0.02em) | `--accent-text` (#a78bfa) | None |
| Footer text | `--font-body` (Inter) | `--text-small` (14px) | 400 | `--leading-body` (1.6) | `--tracking-body` (0) | `--text-muted` (#6b6d85) | None |

### How typography alone creates visual interest

1. **Scale contrast**: The 72px Instrument Serif headline next to 16px Inter body creates a ratio of 4.5:1 in font size. This extreme contrast is the primary source of visual drama on the page. The eye immediately goes to the large serif text, then cascades down through the hierarchy.

2. **Serif/sans tension**: Instrument Serif and Inter are visually distinct families. The contrast between the serif display type (organic, calligraphic, high stroke contrast) and the sans body (geometric, uniform, mechanical) creates a push-pull that keeps the eye engaged. This pairing says "editorial authority meets technical precision."

3. **Eyebrow rhythm**: Every section starts with a small, uppercase, tracked-wide, violet-colored eyebrow label in Inter, followed immediately by a large serif headline in Instrument Serif. This PATTERN creates rhythm -- the reader learns the visual cadence and can scan efficiently. The eyebrow is like a chapter number; the headline is the chapter title.

4. **Whitespace as punctuation**: Large gaps between sections (128px at desktop) and generous padding inside cards (32px) create visual "silences" that make the typography louder by contrast. The page has MORE whitespace than A or B, which paradoxically makes it feel more confident, not more empty.

5. **Monospace as texture**: JetBrains Mono appears in metric numbers, pipeline labels, and inline code references. Each appearance signals "this is precise data" and creates a visual interruption in the sans-serif flow that adds interest without requiring decoration.

---

## 5. Shape and Composition

### Dominant shape primitives

**Sharp rectangles with VERY subtle rounding.** Not the 16px radius of the existing tokens. Not fully sharp either. A 6px radius on cards, 4px on buttons, 0px on section containers. The slight rounding softens what would otherwise feel brutalist, while remaining far more angular than the rounded-rectangle aesthetic of most SaaS pages.

```css
:root {
  --radius-none: 0px;       /* Section containers, full-width elements */
  --radius-xs: 4px;         /* Buttons, inputs, tags, badges */
  --radius-sm: 6px;         /* Cards, bento items, pricing cards */
  --radius-md: 8px;         /* Modal dialogs, larger containers */
  --radius-full: 9999px;    /* Pills only (used very sparingly) */
}
```

Why sharper shapes: rounded rectangles signal "friendly consumer app." Sharp rectangles signal "professional tool." The editorial direction needs the latter. The 6px card radius prevents the page from feeling hostile while maintaining the sharp, precise aesthetic.

### Card treatment

Every card follows the same internal structure. This consistency is fundamental to the editorial bento approach -- the reader learns the pattern once and can scan every card efficiently.

```
┌─────────────────────────────────────┐
│  EYEBROW LABEL                (13px, uppercase, tracked, violet)
│                                      │
│  Card Title                    (18-22px, Inter semibold, primary)
│                                      │
│  Card body text. One to three        │
│  lines maximum. Concise.       (16px, Inter regular, secondary)
│                                      │
└─────────────────────────────────────┘
```

Card CSS:

```css
.card {
  background: var(--surface-1);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: var(--radius-sm);  /* 6px */
  padding: 32px;

  /* NO box-shadow at rest. Flat. The border alone provides definition.
     Shadow only appears on hover (see Motion section). */
  box-shadow: none;
}
```

Cards have NO icons. No decorative illustrations. No emoji. The eyebrow label replaces the icon as the category identifier. This is a deliberate editorial choice: icons are visual noise when the text is clear enough.

Exception: the how-it-works section uses a small layer number (L1, L2, L3) set in JetBrains Mono inside a 32px square with an accent border. This is informational, not decorative.

### Section layout patterns

The page uses three layout patterns, alternating to create visual variety:

**Pattern A: Centered editorial** (hero, differentiator, final CTA)
- Content centered, max-width 800px
- Large serif headline, centered
- Body text centered, max-width 600px within the 800px container
- CTA centered below

**Pattern B: Bento grid** (features, how-it-works)
- Full 6-column grid at desktop, max-width 1400px
- Cards fill the grid with intentional size variation
- Section headline centered above the grid

**Pattern C: Asymmetric split** (problem, solution, social proof)
- Left column: large serif headline + eyebrow (40% width)
- Right column: cards or content blocks (60% width)
- Creates visual variety between the centered and grid sections

### Bento grid approach

The bento grid is the centerpiece of the features section. It uses a 6-column grid at desktop with cards spanning 2 or 3 columns to create visual hierarchy within the grid.

```css
.bento-grid {
  display: grid;
  gap: 16px;  /* Tighter than existing 32px. Editorial density. */
  max-width: 1400px;
  margin: 0 auto;
  padding: 0 24px;
  grid-template-columns: repeat(6, 1fr);
}

/* Card sizing */
.bento-card--wide { grid-column: span 3; }   /* Half-row: 50% */
.bento-card--narrow { grid-column: span 2; } /* Third-row: 33% */
.bento-card--full { grid-column: span 6; }   /* Full-row: rare, for emphasis */
```

**Grid layout for 6 feature cards:**
```
Row 1: [-----wide (span 3)-----] [-----wide (span 3)-----]
Row 2: [--narrow (2)--] [--narrow (2)--] [--narrow (2)--]
```

This 2+3 pattern creates visual rhythm: the top row has two large "hero" feature cards, the bottom row has three smaller supporting cards. The top two cards get more copy and a slightly larger title.

At tablet (max-width 1024px): 4-column grid, wide = span 2, narrow = span 2.
At mobile (max-width 640px): 1-column, all cards full-width, stacked.

### Whitespace as a design element

Whitespace is not filler. It is the frame. The page uses generous spacing that would feel empty on a glow-heavy page but feels intentional and premium here because the typography is strong enough to hold the space.

```css
:root {
  /* Between major sections: 128px at desktop, 80px at mobile. */
  --section-gap: clamp(5rem, 8vw, 8rem);

  /* Section internal padding (top + bottom): 96px at desktop, 64px at mobile. */
  --section-padding: clamp(4rem, 6vw, 6rem);

  /* Between section headline and content: 64px at desktop. */
  --headline-to-content: clamp(2.5rem, 4vw, 4rem);

  /* Between eyebrow and headline: 12px. Tight coupling. */
  --eyebrow-to-headline: 0.75rem;

  /* Card internal padding: 32px all sides at desktop, 24px at mobile. */
  --card-padding: clamp(1.5rem, 2vw, 2rem);
}
```

**Rule**: No section may have less than 80px of vertical padding. No card may have less than 24px of internal padding. These minimums are hard constraints, not suggestions.

### How information density is achieved without clutter

1. **Consistent card structure**: Every card has the same eyebrow-title-body pattern. The reader's eye learns where to look, so scanning is fast even with dense content.

2. **Tight grid gaps (16px) with generous card padding (32px)**: The cards feel spacious internally while the grid itself is compact. This creates a "magazine spread" density.

3. **No decorative elements**: No icons, no illustrations, no background patterns. Every pixel is either text, whitespace, or a structural border. This means more content fits without visual competition.

4. **Hierarchical scanning**: The large serif headlines are entry points. Eyebrows are categories. Card titles are scannable summaries. Body text is optional depth. Four levels of hierarchy allow the reader to choose their depth of engagement.

---

## 6. Motion System

### The ONE "wow" in skin

**Typographic accent treatment on the hero headline.**

One or two words in the hero headline are set in `--accent-text` (#a78bfa) violet. On page load, these words transition from `--text-primary` to `--accent-text` over 800ms with a slight letter-spacing animation (from 0 to -0.025em), as if the word is "focusing" into its final form. This is the only moment of visual drama on the page.

```css
.hero__headline-accent {
  color: var(--text-primary);
  letter-spacing: 0.02em;
  transition: color 800ms cubic-bezier(0.0, 0.0, 0.2, 1.0),
              letter-spacing 800ms cubic-bezier(0.0, 0.0, 0.2, 1.0);
}

.hero__headline-accent.is-loaded {
  color: var(--accent-text);
  letter-spacing: var(--tracking-display);
}
```

This is subtle. A viewer who blinks will miss it. But the ones who see it will register it as quality. The constraint: this animation happens ONCE, on initial load. It does not repeat. It is not scroll-triggered. It fires 300ms after page load (allowing fonts to settle).

### The ONE "wow" in behavior

**Card hover: border-accent reveal with content shift.**

When a bento card is hovered, three things happen simultaneously:
1. The left border transitions from `rgba(255,255,255,0.08)` to `var(--accent)` (#7c5cfc) -- a 2px left border that "lights up"
2. The card title color transitions from `--text-primary` to `--accent-text`
3. The card body text shifts up 2px (translateY(-2px)) -- a nearly imperceptible lift that creates kinetic feedback

```css
.bento-card {
  border-left: 2px solid transparent;
  transition:
    border-color 200ms cubic-bezier(0.25, 0.1, 0.25, 1.0),
    background 200ms cubic-bezier(0.25, 0.1, 0.25, 1.0);
}

.bento-card:hover {
  border-left-color: var(--accent);
  background: var(--surface-2);
}

.bento-card__title {
  transition: color 200ms cubic-bezier(0.25, 0.1, 0.25, 1.0);
}

.bento-card:hover .bento-card__title {
  color: var(--accent-text);
}

.bento-card__body {
  transition: transform 200ms cubic-bezier(0.25, 0.1, 0.25, 1.0);
}

.bento-card:hover .bento-card__body {
  transform: translateY(-2px);
}
```

This hover pattern is the page's signature interaction. It appears on bento cards, problem cards, solution cards, pricing cards, and FAQ items (adapted per context). The left-border accent reveal is the connective thread.

### Entrance animations

Scroll-triggered entrance animations are SUBTLE and FAST. No dramatic fly-ins. No scale transforms. Just opacity.

```css
[data-animate] {
  opacity: 0;
  transition: opacity 400ms cubic-bezier(0.0, 0.0, 0.2, 1.0);
}

[data-animate].is-visible {
  opacity: 1;
}
```

That is the entire entrance animation system. Opacity only. No translateY, no scale, no rotation. Elements simply fade in over 400ms. This is intentional: the page is about clarity, and elements jumping around undermine clarity. The existing 32px translateY in Directions A/B makes the page feel like it's "building itself." Direction C's page already looks built; you're just seeing more of it.

**Stagger**: When multiple elements in a section enter together, each is delayed by 60ms (not 80ms -- faster stagger for a snappier feel). Maximum stagger group: 6 items.

```javascript
// Intersection Observer callback
entries.forEach(entry => {
  if (entry.isIntersecting) {
    const group = entry.target.closest('[data-stagger-group]');
    if (group) {
      const items = group.querySelectorAll('[data-animate]');
      items.forEach((item, index) => {
        const delay = Math.min(index, 5) * 60; // cap at 6 items
        item.style.transitionDelay = `${delay}ms`;
        item.classList.add('is-visible');
      });
    } else {
      entry.target.classList.add('is-visible');
    }
    observer.unobserve(entry.target);
  }
});
```

### Hover states (where delight lives)

| Element | Hover behavior | Duration | Easing |
|---------|---------------|----------|--------|
| Bento card | Left border accent + title color + body lift 2px | 200ms | ease-standard |
| Problem card | Left border accent + title color | 200ms | ease-standard |
| Solution layer card | Left border accent + layer number background fills | 200ms | ease-standard |
| Pricing card | Left border accent + tier name color | 200ms | ease-standard |
| FAQ question | Left border accent + question text color | 200ms | ease-standard |
| CTA button | Background lightens to `--accent-light`, translateY(-1px) | 150ms | ease-standard |
| Secondary button | Border color shifts to `--accent`, text shifts to `--accent-text` | 150ms | ease-standard |
| Nav link | Color shifts from `--text-secondary` to `--text-primary` | 150ms | ease-standard |
| Footer link | Color shifts to `--accent-text` | 150ms | ease-standard |

### What does NOT animate

- **Section backgrounds**: No color transitions, no gradient shifts. Static.
- **Headlines**: No entrance animations on section headlines beyond opacity fade. No glitch effects, no typewriter, no gradient reveals.
- **The pipeline visualization**: The dots travel along the track (informational), but the gates and labels do not animate on hover. They are static structural elements.
- **Card backgrounds at rest**: No ambient pulsing. No glow cycling. Cards are static until hovered.
- **Images/illustrations**: There are none, but if any are added later, they do not animate.
- **Typography**: No animated letter-spacing except the ONE hero accent word on load. No animated font sizes. No text color cycling.

### Reduced motion

```css
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }

  [data-animate] {
    opacity: 1 !important;
    transform: none !important;
    transition-delay: 0ms !important;
  }
}
```

---

## 7. Section-by-Section Visual Treatment

### 7.1 Hero

**Background**: `--bg-primary` (#0c0d14). Flat. No gradient, no orbs, no mesh. The hero's visual interest comes entirely from the typography.

**Layout**: Pattern A (centered editorial). Content constrained to `max-width: 800px`, centered.

```
[                                                        ]
[                                                        ]
[                    THE PROBLEM                         ]  <- eyebrow (13px, violet, uppercase, tracked)
[                                                        ]  <- 12px gap
[            Your AI writes the code.                    ]  <- display (Instrument Serif, 72px, white)
[            Who checks if it's right?                   ]
[                                                        ]  <- 24px gap
[        Multiple AI specialists write, review, and      ]  <- body-lg (Inter, 18px, secondary)
[        organize your code through quality gates —      ]
[        so nothing ships broken.                        ]
[                                                        ]  <- 32px gap
[             [ JOIN THE WAITLIST ]                       ]  <- primary CTA
[             See how it works ->                        ]  <- secondary CTA (text link with arrow)
[                                                        ]  <- 16px gap
[         Be first when we launch. No credit card.       ]  <- caption (12px, muted)
[                                                        ]
```

**Typography choices**:
- Eyebrow: "THE PROBLEM WITH AI CODE" -- sets up the headline as the answer
- Headline: Instrument Serif. The word "right" is the accent word that transitions to violet on load
- Subhead: Inter regular, `--text-secondary`
- CTAs: primary button + secondary text link (not two buttons -- the ghost button competes visually with the primary)

**Visual elements**: None beyond text and the two CTAs. The hero's power comes from the large serif headline on the flat dark background. No pipeline diagram here (that moves to the how-it-works section where it has context).

**Hover/interaction**:
- Primary CTA: background lightens, shifts up 1px
- Secondary CTA ("See how it works"): underline appears on hover, smooth 150ms
- Hero accent word ("right"): transitions to violet 300ms after page load (the ONE skin wow)

**Scroll indicator**: A subtle downward-pointing chevron at the bottom of the viewport, centered. Fades in at 1s after page load, gently bounces 4px with a 2s loop. Disappears as soon as user scrolls (opacity: 0 on scroll).

```css
.hero__scroll-cue {
  position: absolute;
  bottom: 32px;
  left: 50%;
  transform: translateX(-50%);
  opacity: 0;
  animation: scrollCueFade 1s 1s forwards, scrollCueBounce 2s 1.5s infinite;
  color: var(--text-muted);
  font-size: 20px;
}

@keyframes scrollCueFade {
  to { opacity: 0.5; }
}

@keyframes scrollCueBounce {
  0%, 100% { transform: translateX(-50%) translateY(0); }
  50% { transform: translateX(-50%) translateY(4px); }
}
```

**Dimensions**: `min-height: 100vh`. On mobile (below 640px), `min-height: auto` with `padding-top: 80px; padding-bottom: 64px`.

---

### 7.2 Problem Section ("The truth about AI coding")

**Background**: `--bg-secondary` (#13141e). The first section break -- the background change should be noticeable.

**Layout**: Pattern C (asymmetric split).

```
[                                                                    ]
[  THE TRUTH ABOUT AI CODE     |   ┌─────────────────────────────┐   ]
[                              |   │ CARD 1                      │   ]
[  Why your AI-generated       |   │ AI forgets things           │   ]
[  code keeps breaking         |   │ Your AI handles small tasks │   ]
[                              |   │ fine. But as your project...│   ]
[  (left column holds the      |   └─────────────────────────────┘   ]
[   section headline only,     |   ┌─────────────────────────────┐   ]
[   sticky-positioned)         |   │ CARD 2                      │   ]
[                              |   │ AI takes shortcuts          │   ]
[                              |   │ AI models optimize to look  │   ]
[                              |   │ correct. They hardcode...   │   ]
[                              |   └─────────────────────────────┘   ]
[                              |   ┌─────────────────────────────┐   ]
[                              |   │ CARD 3                      │   ]
[                              |   └─────────────────────────────┘   ]
[                              |   ┌─────────────────────────────┐   ]
[                              |   │ CARD 4                      │   ]
[                              |   └─────────────────────────────┘   ]
[                                                                    ]
```

The left column (40% width) contains the eyebrow + section headline in Instrument Serif. The headline is `position: sticky; top: 128px` so it stays visible as the user scrolls through the cards on the right. At mobile (below 768px), the layout collapses to single-column with the headline on top, cards stacked below.

**Typography**:
- Eyebrow: "THE TRUTH ABOUT AI CODE" (13px, violet, uppercase, tracked)
- Section headline: "Why your AI-generated code keeps breaking" (Instrument Serif, 32-48px)
- Card eyebrows: none (the problem cards use the card title as the primary hook)
- Card titles: "AI forgets things" (Inter semibold, 18-22px)
- Card body: 2-3 sentences (Inter regular, 16px, `--text-secondary`)

**Visual elements**: Each card has a subtle left-border that is transparent at rest. On hover, it transitions to `--accent` (violet), making the card feel "selected."

**Hover/interaction**: Left-border accent reveal. Card title shifts to `--accent-text`. This is the standard card hover pattern.

**Entrance**: Cards fade in (opacity only) with 60ms stagger.

---

### 7.3 Solution Section ("A team of AI specialists, working for you")

**Background**: `--bg-primary` (#0c0d14). Returns to base.

**Layout**: Pattern A (centered editorial) for the headline, then a custom 3-card horizontal layout for the three layers.

```
[                                                                    ]
[                         THE SOLUTION                               ]
[                                                                    ]
[             A team of AI specialists,                              ]
[             working for you                                        ]
[                                                                    ]
[  Instead of trusting one AI to do everything,                      ]
[  Spec Manager uses multiple AI specialists —                       ]
[  each with a different job, each checking                          ]
[  the others' work.                                                 ]
[                                                                    ]
[  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐            ]
[  │ L1           │    │ L2           │    │ L3           │            ]
[  │ BUILD        │    │ ORGANIZE     │    │ POLISH       │            ]
[  │              │    │              │    │              │            ]
[  │ AI writes    │    │ Architecture │    │ Code quality │            ]
[  │ code from    │    │ reviewers    │    │ reviewers    │            ]
[  │ your spec... │    │ check the    │    │ verify       │            ]
[  │              │    │ design...    │    │ clarity...   │            ]
[  └─────────────┘    └─────────────┘    └─────────────┘            ]
[                                                                    ]
```

Each layer card has:
- A layer number badge: "L1" / "L2" / "L3" in JetBrains Mono, 12px, inside a 32x32px box with a 1px accent border and transparent background. On hover, the background fills with `rgba(124, 92, 252, 0.15)`.
- A layer name: "BUILD" / "ORGANIZE" / "POLISH" -- Inter semibold, 13px, uppercase, tracked wide, violet.
- A description: Inter regular, 16px, `--text-secondary`.

A horizontal line runs below the three cards connecting them left to right -- a 1px line using `--gradient-pipeline` (violet to cyan). This is the ONE place the full brand gradient appears. Three small dots (6px circles) sit on this line at each card's center, filled with `--accent`.

**Typography**:
- Eyebrow: "THE SOLUTION" (standard)
- Section headline: Instrument Serif, `--text-h1`
- Intro paragraph: Inter regular, `--text-body-lg`, max-width 600px, centered
- Layer cards: see card structure above

**Hover/interaction**: Layer cards follow the standard left-border accent reveal. On hover, the L1/L2/L3 badge background fills.

**Entrance**: Cards fade in with 60ms stagger (left to right). The pipeline line fades in 200ms after the last card.

---

### 7.4 How It Works (simplified 3-step)

**Background**: `--bg-secondary` (#13141e).

**Layout**: Pattern A (centered editorial) for headline, then three numbered steps stacked vertically with generous spacing.

```
[                                                                    ]
[                       HOW IT WORKS                                 ]
[                                                                    ]
[             Three steps to verified code                           ]
[                                                                    ]
[         01   Describe what you want                                ]
[              Write a spec in plain language.                        ]
[              The system tracks every requirement.                   ]
[                                                                    ]
[         ─────────────────────────────────                          ]
[                                                                    ]
[         02   AI builds it with guardrails                          ]
[              Multiple AI specialists write, review,                ]
[              and organize your code. Bad code gets                 ]
[              sent back. Good code gets promoted.                   ]
[                                                                    ]
[         ─────────────────────────────────                          ]
[                                                                    ]
[         03   Ship with confidence                                  ]
[              Only code that passes every quality gate              ]
[              reaches your codebase.                                ]
[                                                                    ]
```

Each step has:
- Step number: "01" / "02" / "03" in JetBrains Mono, `--text-h2` (24-32px), weight 500, `--text-muted` (#6b6d85). The large mono number serves as a visual anchor.
- Step title: Inter semibold, `--text-h3` (18-22px), `--text-primary`. Sits on the same baseline as the number (inline, with 16px gap).
- Step description: Inter regular, `--text-body` (16px), `--text-secondary`. Left-aligned with the title, indented past the number.

Between steps: a 1px horizontal rule, `rgba(255,255,255,0.08)`, max-width 480px, centered. Not spanning full width -- the truncated line is an editorial device.

**Typography**: The step numbers in JetBrains Mono are the visual feature here. Their large size and muted color make them structural landmarks that the eye uses for navigation.

**Hover/interaction**: None. This section is static. Steps are not interactive. The simplicity is the point.

**Entrance**: Steps fade in with 100ms stagger. The horizontal rules between them fade in at the same time as the step below them.

---

### 7.5 Social Proof Section

**Background**: `--bg-primary` (#0c0d14).

**Layout**: A narrow strip (not a full section). Max-width 1000px, centered. Horizontal layout at desktop, stacked at mobile.

Since there are no customer testimonials, logos, or case studies (pre-launch product), this section uses builder credibility and technical metrics:

```
[                                                                    ]
[     723                52/52              25+                       ]
[     tests passing      requirements       years building           ]
[                        tracked            developer tools          ]
[                                                                    ]
[     Works with Claude Code, Cursor, Windsurf, and more.            ]
[                                                                    ]
```

Three metric blocks side by side:
- Number: JetBrains Mono, `--text-h2` (24-32px), weight 500, `--text-primary`
- Label: Inter regular, `--text-small` (14px), `--text-muted`

Below: a single line of text listing integrations, Inter regular, `--text-small`, `--text-secondary`, centered.

**Typography**: The mono metric numbers are the focal point. Their size (32px) and monospace character provide visual weight without decoration.

**Visual elements**: A 1px horizontal rule above and below this strip, full-width, `rgba(255,255,255,0.06)`. These thin lines frame the proof strip and differentiate it from the sections above and below.

**Hover/interaction**: None. Proof is static.

**Entrance**: All three metrics fade in simultaneously. No stagger (they should appear as a group, not a sequence).

---

### 7.6 Features (Bento Grid)

**Background**: `--bg-secondary` (#13141e).

**Layout**: Pattern B (bento grid). 6-column grid at desktop, max-width 1400px.

```
[                                                                    ]
[                         FEATURES                                   ]
[                                                                    ]
[             What you get                                           ]
[                                                                    ]
[  ┌──────────────────────────┐ ┌──────────────────────────┐        ]
[  │ MULTI-MODEL              │ │ QUALITY GATES             │        ]
[  │                          │ │                           │        ]
[  │ Multiple AIs,            │ │ Nothing ships without     │        ]
[  │ not just one             │ │ earning it                │        ]
[  │                          │ │                           │        ]
[  │ Different AI models      │ │ Code moves through        │        ]
[  │ handle different jobs.   │ │ quality gates. Failures   │        ]
[  │ Writers, reviewers...    │ │ get demoted back...       │        ]
[  └──────────────────────────┘ └──────────────────────────┘        ]
[  ┌────────────────┐ ┌────────────────┐ ┌────────────────┐         ]
[  │ TRACKING       │ │ CLARITY        │ │ PERSISTENCE    │         ]
[  │                │ │                │ │                │         ]
[  │ Every          │ │ AI asks,       │ │ Walk away      │         ]
[  │ requirement    │ │ not guesses    │ │ and come back  │         ]
[  │ tracked        │ │                │ │                │         ]
[  │                │ │ When something │ │ State persists │         ]
[  │ A coverage     │ │ is ambiguous,  │ │ across         │         ]
[  │ ledger maps... │ │ the system...  │ │ sessions...    │         ]
[  └────────────────┘ └────────────────┘ └────────────────┘         ]
[                                                                    ]
```

Row 1: two wide cards (span 3 each). These are the two most important features.
Row 2: three narrow cards (span 2 each). Supporting features.

Card 6 ("Your process, your rules") is omitted from the grid and instead appears as a single line of text below the grid: "Customize workflows. Choose your AI models. Define how work gets done." in Inter regular, `--text-body`, `--text-secondary`, centered. This prevents a third row that would either have one wide card awkwardly alone or require layout gymnastics.

**Typography**:
- Eyebrow on each card: feature category (e.g., "MULTI-MODEL", "QUALITY GATES") in 13px, uppercase, tracked, violet
- Card title: Inter semibold, 18-22px
- Card body: Inter regular, 16px, `--text-secondary`, max 3 lines

**Hover/interaction**: Standard left-border accent reveal on every card.

**Entrance**: Cards fade in with 60ms stagger. Row 1 cards first, then Row 2.

---

### 7.7 Differentiator ("Not another AI code generator")

**Background**: `--bg-feature` (#181a26) -- the special "feature" background used only here. Slightly warmer and lighter than the other backgrounds, making this section feel distinct.

**Layout**: Pattern A (centered editorial). Max-width 800px, centered.

```
[                                                                    ]
[                     WHAT MAKES US DIFFERENT                        ]
[                                                                    ]
[          Other tools help you write code                           ]
[          faster. We make sure it's right.                          ]
[                                                                    ]
[          They build. We build and verify.                          ]
[          They hope for the best. We check the work.               ]
[          They give you speed. We give you                          ]
[          speed and confidence.                                     ]
[                                                                    ]
```

This section is ALL typography. No cards. No grid. No visual elements. The section headline is the statement, and the body copy below it uses a pattern of repeated sentence structures ("They... We...") that creates rhythm through text alone.

**Typography**:
- Eyebrow: "WHAT MAKES US DIFFERENT" (standard)
- Section headline: Instrument Serif, `--text-h1`. The word "right" (or "it's right") is set in `--accent-text` violet
- Body copy: Inter regular, `--text-body-lg` (18px), `--text-secondary`. Each "They..." / "We..." pair is its own paragraph with 16px margin-bottom. The "We..." portions are set in `--text-primary` (white) for emphasis.

```css
.diff__emphasis {
  color: var(--text-primary);
  font-weight: 500;
}
```

**Hover/interaction**: None. This section is pure text. The only interactive element is if it contains a CTA (optional -- could place a "Join the Waitlist" button below the text).

**Entrance**: Section headline fades in, then body paragraphs fade in with 60ms stagger.

---

### 7.8 Pricing

**Background**: `--bg-primary` (#0c0d14).

**Layout**: Pattern A (centered editorial) for headline, then a 3-column card layout.

```
[                                                                    ]
[                          PRICING                                   ]
[                                                                    ]
[             Simple, transparent pricing                            ]
[                                                                    ]
[  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐   ]
[  │ FREE             │  │ HYBRID           │  │ CLOUD            │   ]
[  │                  │  │                  │  │                  │   ]
[  │ $0               │  │ $15              │  │ TBD              │   ]
[  │ /month           │  │ /month           │  │                  │   ]
[  │                  │  │                  │  │                  │   ]
[  │ • Runs local     │  │ • Remote mgmt   │  │ • Fully managed  │   ]
[  │ • Full privacy   │  │ • Easier setup  │  │ • Easiest UX     │   ]
[  │ • BYOK           │  │ • Use your subs │  │ • Future         │   ]
[  │ • At launch      │  │ • Coming soon   │  │                  │   ]
[  │                  │  │                  │  │                  │   ]
[  │ [JOIN WAITLIST]  │  │ [JOIN WAITLIST]  │  │ [NOTIFY ME]      │   ]
[  └─────────────────┘  └─────────────────┘  └─────────────────┘   ]
[                                                                    ]
```

Pricing cards are taller than bento cards, with more internal padding (40px vertical, 32px horizontal).

**Typography per pricing card**:
- Tier name: "FREE" / "HYBRID" / "CLOUD" in 13px, uppercase, tracked, violet (eyebrow pattern)
- Price: Instrument Serif, `--text-h1` (32-48px), `--text-primary`. This is the display number. "TBD" renders the same way.
- Period: "/month" in Inter regular, `--text-small` (14px), `--text-muted`, inline with the price
- Feature list: Inter regular, `--text-small` (14px), `--text-secondary`, with bullet points (small circles, not checkmarks)
- CTA button: inside each card, full-width

The middle card (Hybrid, $15/mo) has no special treatment. No "recommended" badge, no border highlight. All three cards are visually equal. The Free tier's $0 speaks for itself.

**Hover/interaction**: Standard left-border accent reveal. On hover, the tier name color does not change (it is already violet).

**Entrance**: Three cards fade in simultaneously. No stagger (pricing should feel complete and stable, not sequential).

---

### 7.9 FAQ

**Background**: `--bg-secondary` (#13141e).

**Layout**: Pattern A (centered editorial). Max-width 700px for the FAQ items. Narrow -- FAQ answers should be readable without wide line lengths.

```
[                                                                    ]
[                        QUESTIONS                                   ]
[                                                                    ]
[  ─────────────────────────────────────────────────                 ]
[  Is this just another Cursor/Copilot?                    [+]       ]
[  ─────────────────────────────────────────────────                 ]
[  Do I need to know how to code?                          [+]       ]
[  ─────────────────────────────────────────────────                 ]
[  What if I already use Cursor?                           [+]       ]
[  ─────────────────────────────────────────────────                 ]
[  Is my code private?                                     [+]       ]
[  ─────────────────────────────────────────────────                 ]
[  When does it launch?                                    [+]       ]
[  ─────────────────────────────────────────────────                 ]
[                                                                    ]
```

FAQ items use `<details>/<summary>` elements. Separated by 1px horizontal rules (`rgba(255,255,255,0.08)`). The expand/collapse indicator is a simple "+" that rotates 45 degrees to become an "x" when open.

**Typography**:
- Section headline: "Questions" (just the one word -- Instrument Serif, `--text-h1`). No eyebrow needed; the heading is self-explanatory.
- Question text: Inter semibold, `--text-h3` (18-22px), `--text-primary`
- Answer text: Inter regular, `--text-body` (16px), `--text-secondary`, with 16px top padding when expanded
- Expand indicator: Inter light, 20px, `--text-muted`

**Hover/interaction**: Standard left-border accent reveal on each FAQ item. The question text shifts to `--accent-text` on hover.

The expand/collapse animation: answer content height transitions from 0 to auto over 250ms. The "+" rotates to "x" over 200ms.

```css
.faq__toggle {
  transform: rotate(0deg);
  transition: transform 200ms cubic-bezier(0.25, 0.1, 0.25, 1.0);
}

.faq__item[open] .faq__toggle {
  transform: rotate(45deg);
}
```

**Entrance**: FAQ items fade in with 60ms stagger.

---

### 7.10 Final CTA

**Background**: `--bg-primary` (#0c0d14). Flat. No special background treatment -- the CTA earns attention through typography, not atmosphere.

**Layout**: Pattern A (centered editorial). Max-width 600px for the form area.

```
[                                                                    ]
[                                                                    ]
[                                                                    ]
[              Ready to ship code                                    ]
[              you can trust?                                        ]
[                                                                    ]
[              Be the first to know when we launch.                  ]
[                                                                    ]
[         [      your@email.com      ] [JOIN THE WAITLIST]           ]
[                                                                    ]
[              No credit card required. Just your email.             ]
[                                                                    ]
[                                                                    ]
[                                                                    ]
```

**Typography**:
- No eyebrow (the CTA headline replaces it)
- Headline: Instrument Serif, `--text-h1` (32-48px), `--text-primary`. "trust" is set in `--accent-text` violet.
- Subhead: Inter regular, `--text-body-lg` (18px), `--text-secondary`
- Friction reducer: Inter regular, `--text-caption` (12px), `--text-muted`

**Visual elements**: The email form is inline: input + button side by side at desktop, stacked at mobile. Input has a 1px border, `rgba(255,255,255,0.10)`, `--radius-xs` (4px). Button is the standard primary CTA.

The section has generous vertical padding: 128px top, 128px bottom (at desktop). This extra breathing room around the final CTA gives it gravitas.

**Hover/interaction**:
- Email input: on focus, border shifts to `--accent`, 3px box-shadow ring `rgba(124, 92, 252, 0.20)`
- CTA button: standard hover behavior

**Entrance**: Headline fades in, then form fades in 200ms later.

---

## 8. Strengths and Risks

### Strengths

1. **Distinctive in the market**: No competitor uses editorial serif typography for a devtool landing page. Cursor, Windsurf, Replit, Bolt, and Devin all use sans-serif across the board. The serif display headlines immediately distinguish Spec Manager visually.

2. **Typography ages well**: Atmospheric effects (glows, gradients, particles) become dated as trends shift. Strong typography does not. An editorially typeset page will look as good in 2028 as it does in 2026.

3. **Performance is inherent**: No glow orbs, no mesh gradients, no ambient animations (besides a single pipeline flow). The page is primarily text and CSS. First contentful paint will be fast. Total JS under 3KB (just IntersectionObserver setup). Total CSS under 30KB.

4. **Accessibility is built-in**: High contrast text on flat dark backgrounds. No color-dependent information. No motion-dependent content. Reduced motion support is trivial because there is almost no motion to begin with. WCAG AA compliance at every text level.

5. **Information density**: The editorial approach compresses more information into less space because it does not need visual decorations, icons, or illustrations to fill the layout. Every pixel is either meaningful content or intentional whitespace.

6. **Copy does the selling**: This direction puts ALL emphasis on the words. If the copywriting is strong (and the messaging strategy suggests it is), the page will convert well because nothing competes with the copy for attention.

7. **Scannable**: The consistent card structure (eyebrow-title-body) and the strong typographic hierarchy (serif headlines / sans body / mono accents) create a page that can be scanned in 10 seconds or read in 3 minutes. Both paths work.

### Risks

1. **Requires excellent copy**: This direction strips away every visual crutch. If the copy is weak, generic, or too long, the page will feel like a wall of text. There are no illustrations to break monotony, no glows to add interest, no animations to create engagement. The writing must carry everything. Mitigation: the messaging strategy is strong, and the copy is already written.

2. **Might feel too "quiet" for vibe coders**: The target audience is excited by AI and may expect a more visually dynamic page (like Direction A's glowing pipeline or Direction B's scroll story). Direction C's restrained approach might not match their emotional expectations. Mitigation: the serif display type adds visual drama, and the clean confidence projects "professional tool" rather than "another AI toy."

3. **Serif font risk**: Instrument Serif is relatively new (2023). While it is well-crafted, it may render inconsistently on older browsers or non-standard OS font rendering stacks. The fallback to Georgia is acceptable but noticeably different. Mitigation: test on Windows ClearType and Android rendering before committing.

4. **No visual metaphor for the pipeline**: Directions A and B both have animated pipeline visualizations in the hero. Direction C moves the pipeline to the solution section and presents it as a static line with dots. This is more "correct" (the pipeline is a solution, not a hook) but may make the hero feel text-only. Mitigation: the hero IS text-only, and that is the point. The typography is the visual.

5. **Dark mode fatigue**: While this direction uses a dark background, it is not as warm or atmospheric as Direction A. Users who are fatigued by dark-mode devtool sites may not see it as differentiated. Mitigation: the editorial typography is the differentiation, not the color scheme. The dark background is a canvas, not an experience.

6. **The bento grid 16px gap is tight**: At 16px gap between cards, the grid feels dense. If card copy runs long, cards may feel cramped. Mitigation: enforce strict copy limits (3 lines max per card body) and test at all breakpoints. If too tight, 20px is acceptable without losing the editorial density.

7. **No social proof assets**: This is a pre-launch product constraint, not a Direction C constraint. But the risk is amplified here because this direction has no visual atmosphere to compensate for the absence of proof. The page is clean and direct, which means the missing testimonials and logos are more noticeable. Mitigation: the metrics strip (723 tests, 52/52 requirements, 25+ years) is positioned deliberately as proof.
