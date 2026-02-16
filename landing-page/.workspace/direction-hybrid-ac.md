# Hybrid Direction: Precision Editorial with Controlled Atmosphere

**Date:** 2026-02-14
**Basis:** Direction C (editorial typography) + Direction A (pipeline atmosphere) + Direction B (narrative structure)
**Core thesis:** The page reads like a beautifully typeset specification document that reveals a glowing pipeline system beneath its surface. Serif display headlines create instant visual distinction. Atmosphere is reserved for two bookend moments (hero and final CTA). Everything between is clean, editorial, information-dense.

---

## 1. Direction Summary

This direction combines editorial typography (Instrument Serif display headlines, strong typographic hierarchy) with controlled atmospheric energy (mesh-gradient hero, pipeline gate illumination) and narrative structure (background temperature shifts, gradient as story device). The result is a page that looks unlike any competitor in the devtools space (serif typography is unique) while delivering the atmospheric energy that vibe coders expect (dark theme, pipeline glow).

The ONE wow in skin: Instrument Serif headlines on dark atmospheric backgrounds. No devtools competitor uses serif display type. This is the instant visual differentiator.

The ONE wow in behavior: Sequential pipeline gate illumination on scroll. When the hero pipeline enters the viewport, gates light up one at a time with glow halos and checkmark reveals. This directly illustrates the product mechanism.

---

## 2. Visual Metaphor

**The published specification with a live system beneath.**

The page reads like a precision-typeset technical document. Instrument Serif headlines create editorial authority. Clean card grids present information densely and scannably. The overall feeling is "this was authored with care, by people who understand precision."

Beneath this editorial surface, a quality pipeline glows. It appears in the hero as an atmospheric mesh, crystallizes in the solution section as a visible pipeline diagram, and returns in the final CTA as a warm glow. The pipeline is not decoration. It is the product made visible.

---

## 3. Color System

### Background treatment

Background shifts temperature across the page (from B's narrative approach) using C's higher contrast between surface levels:

```css
:root {
  --bg-primary: #0a0b10;     /* Hero, solution, features, final CTA */
  --bg-secondary: #0f1018;   /* Problem, how-it-works, FAQ */
  --bg-feature: #13141e;     /* Differentiator only -- warmer, editorial */
}
```

The 5-point jump between primary and secondary is reinforced by 1px gradient divider lines between sections (from A). The differentiator section uses a third, warmer background to break monotony.

### Surface hierarchy

Cards must visibly lift from backgrounds (C's editorial emphasis):

```css
:root {
  --surface-1: #14151f;      /* Card resting state */
  --surface-2: #1a1b28;      /* Card hover / active */
  --surface-3: #212333;      /* Tooltips, popovers */
}
```

### Text hierarchy

```css
:root {
  --text-display: #ffffff;    /* Hero headline only (Instrument Serif) */
  --text-primary: #edeef2;   /* Section headlines, card titles */
  --text-secondary: #9496a8; /* Body text, descriptions */
  --text-muted: #5c5e72;     /* Captions, metadata, friction reducers */
}
```

### Accent usage

Single accent axis: violet. Used surgically (C's accent budget rule).

```css
:root {
  --accent: #7c5cfc;         /* CTA buttons, pipeline gates, brand */
  --accent-light: #a78bfa;   /* Eyebrow text, accent text, links */
  --accent-dark: #5a3de8;    /* Pressed states */
  --success: #34d399;        /* Checkmarks, passed indicators */
  --error: #f87171;          /* Problem icons */
  --warning: #fbbf24;        /* Warning icons */
  --cyan: #00d4ff;           /* Pipeline "verified" end, active gates */
}
```

**Accent budget rule (from C):** On any viewport, accent violet appears in max 3 elements: CTA button, one typographic accent, one structural element. If a fourth needs accent, one reverts to neutral.

### Gradient strategy

Gradients appear in specific structural roles, never arbitrarily:

1. **Hero atmospheric mesh** (from A): Three blurred radial gradients creating ambient depth. Violet/cyan/deep-violet orbs at low opacity (0.06-0.12). Drift on 8s loops. Confined to hero + final CTA (at 60% intensity).

2. **Brand identity gradient** (`linear-gradient(135deg, #7c5cfc 0%, #00d4ff 100%)`): Applied as `background-clip: text` on the hero headline accent word and the nav logo. This IS the brand mark.

3. **Pipeline track gradient** (`linear-gradient(90deg, #7c5cfc 0%, #a78bfa 33%, #38bdf8 66%, #00d4ff 100%)`): 2px top-border on pipeline tracks. Four stops showing quality progression.

4. **Section divider lines** (`linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.10) 20%, rgba(255,255,255,0.10) 80%, transparent 100%)`): 1px lines at section boundaries.

5. **Card hover shine** (from A): `linear-gradient(135deg, rgba(255,255,255,0.04) 0%, transparent 50%)` as `::before`, visible only on hover.

No gradient backgrounds on sections. No gradient card fills. Gradients are edge treatments, text treatments, or atmospheric layers.

### Ambient treatment

**Grain overlay** (from A/B): Full-viewport fixed overlay, SVG feTurbulence filter (baseFrequency: 0.65, numOctaves: 3, monochrome). Opacity: 0.035. Blend: overlay. Pointer events: none. Z-index: 9999.

**Atmospheric orbs** (from A): Hero only + final CTA at 60%. Three large blurred radial gradients that drift slowly. GPU-composited (transform + opacity only).

**Middle sections:** Zero atmosphere. Flat backgrounds with divider lines. The editorial typography carries the visual interest.

---

## 4. Typography System

This is the hybrid's primary differentiator. No competitor uses serif display type.

### Font choices

**Display: Instrument Serif** (Google Fonts, weight 400 only)
- Contemporary editorial serif with high stroke contrast
- Used at 40-72px for hero and section headlines
- Sentence case (never uppercase)
- The "published specification" personality

**Body: Inter** (variable, opsz, weights 400-700)
- Geometric, highly legible, optical sizing
- Industry standard for devtools
- The neutral partner to Instrument Serif

**Mono: JetBrains Mono** (weights 400-500)
- Pipeline gate labels, metric numbers, pricing values, eyebrow labels
- "System voice" vs. Inter's "human voice"

### Google Fonts import

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif&family=Inter:opsz,wght@14..32,400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
```

### Type scale (Perfect Fourth, 1.333 ratio)

```css
:root {
  --text-display: clamp(2.5rem, 5vw + 1.25rem, 4.5rem);  /* 40-72px */
  --text-h1: clamp(2rem, 3vw + 0.75rem, 3rem);            /* 32-48px */
  --text-h2: clamp(1.5rem, 2vw + 0.5rem, 2rem);           /* 24-32px */
  --text-h3: clamp(1.125rem, 1.25vw + 0.25rem, 1.375rem); /* 18-22px */
  --text-body-lg: 1.125rem;                                 /* 18px */
  --text-body: 1rem;                                        /* 16px */
  --text-small: 0.875rem;                                   /* 14px */
  --text-caption: 0.75rem;                                  /* 12px */
  --text-eyebrow: 0.8125rem;                                /* 13px */
}
```

### Complete hierarchy

| Element | Font | Size | Weight | Line height | Letter spacing | Color |
|---------|------|------|--------|-------------|---------------|-------|
| Hero headline | Instrument Serif | --text-display | 400 | 1.05 | -0.025em | #ffffff |
| Hero subhead | Inter | --text-body-lg | 400 | 1.5 | 0 | --text-secondary |
| Eyebrow label | JetBrains Mono | --text-eyebrow | 500 | 1.0 | 0.08em | --accent-light, uppercase |
| Section headline | Instrument Serif | --text-h1 | 400 | 1.15 | -0.02em | --text-primary |
| Card title | Inter | --text-h3 | 600 | 1.25 | 0 | --text-primary |
| Card body | Inter | --text-body | 400 | 1.6 | 0 | --text-secondary |
| Body copy | Inter | --text-body | 400 | 1.6 | 0 | --text-secondary |
| Pipeline gate label | JetBrains Mono | --text-caption | 500 | 1.0 | 0.08em | --cyan (active) / --text-muted (inactive) |
| CTA button | Inter | --text-small | 600 | 1.0 | 0.04em | #ffffff, uppercase |
| Metric number | JetBrains Mono | --text-h2 | 500 | 1.25 | 0.02em | --text-primary |
| Pricing price | Instrument Serif | --text-h1 | 400 | 1.15 | -0.02em | --text-primary |
| FAQ question | Inter | --text-h3 | 600 | 1.25 | 0 | --text-primary |

---

## 5. Shape and Composition

### Shape primitives

**Hybrid approach:** 8px card radius (between C's 6px and A's 16px). Sharp enough to feel editorial, soft enough to not feel brutalist.

```css
:root {
  --radius-xs: 4px;     /* Buttons, inputs */
  --radius-sm: 8px;     /* Cards, bento items */
  --radius-md: 12px;    /* Pricing cards, larger containers */
  --radius-full: 9999px; /* Pills only */
}
```

### Card treatment

Cards use C's editorial structure (eyebrow-title-body) with A's hover effects:

```css
.card {
  background: var(--surface-1);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: var(--radius-sm);
  padding: 28px;
  box-shadow: none;
}

.card:hover {
  background: var(--surface-2);
  border-color: rgba(124, 92, 252, 0.40);
  box-shadow: 0 0 30px rgba(124, 92, 252, 0.12);
}
```

Interactive cards get C's left-border accent reveal on hover + diagonal shine from A.

### Bento grid (6-column)

```
Row 1: [-----wide (span 3)-----] [-----wide (span 3)-----]
Row 2: [--narrow (2)--] [--narrow (2)--] [--narrow (2)--]
Row 3: [--------full width (span 6)--------]
```

Gap: 20px (between C's 16px and A's 32px). Tight enough for editorial density, loose enough for clarity.

### Section layout patterns

**Pattern A: Centered editorial** (hero, differentiator, final CTA)
- Max-width 800px, centered
- Instrument Serif headline, centered
- Body text max-width 600px within container

**Pattern B: Card grid** (features, pricing)
- 6-column bento at 1400px max
- Cards with consistent eyebrow-title-body structure

**Pattern C: Centered + connected cards** (solution, how-it-works)
- Centered headline above
- Three horizontal cards connected by pipeline track

### Whitespace

```css
:root {
  --section-gap: clamp(5rem, 8vw, 8rem);     /* 80-128px between sections */
  --section-padding: clamp(4rem, 6vw, 6rem);  /* 64-96px internal padding */
  --headline-gap: clamp(2rem, 3vw, 3rem);     /* 32-48px headline to content */
  --card-padding: clamp(1.5rem, 2vw, 1.75rem); /* 24-28px internal */
}
```

---

## 6. Motion System

### Skin wow: Instrument Serif + atmospheric mesh (hero/CTA)

The hero and final CTA feature mesh-gradient orbs drifting behind Instrument Serif headlines. This creates a "precision document lit from within" effect. Three orbs at low opacity drift on 8s alternate loops, 30px translate range. GPU-composited.

The middle sections have ZERO atmosphere. The contrast between atmospheric bookends and clean editorial middle sections creates visual breathing.

### Behavior wow: Pipeline gate illumination

When the hero pipeline enters viewport (IntersectionObserver, 0.15 threshold):
1. Gates illuminate sequentially (300ms stagger)
2. Border transitions from neutral to violet (200ms)
3. Glow halo fades in (cyan, 400ms)
4. Gate icon scales 0.9 to 1.0 (400ms, spring easing)
5. Checkmark pops in after glow reaches full intensity

Flow dots (6px) travel along the track (3s linear loop). This fires once, then gates stay illuminated.

### Entrance animations

Scroll-triggered via IntersectionObserver (0.15 threshold). Subtle:

| Element | Transform | Duration | Stagger |
|---------|-----------|----------|---------|
| Section headline | translateY(20px), opacity 0→1 | 500ms | None |
| Body text | translateY(12px), opacity 0→1 | 400ms | 80ms after headline |
| Cards | translateY(24px), opacity 0→1, scale(0.98) | 500ms | 80ms between cards |
| Problem cards | translateX(-32px), opacity 0→1 | 400ms | 80ms between |
| Pipeline gates | Custom illumination sequence | See above | 300ms between gates |
| FAQ items | opacity 0→1 | 400ms | None (individual observers) |

All use decelerate easing: `cubic-bezier(0.0, 0.0, 0.2, 1.0)`.

### Hover states

C's left-border accent reveal is the signature interaction:

| Element | Hover behavior | Duration |
|---------|---------------|----------|
| Bento card | Left border accent + title color shift + body translateY(-2px) + diagonal shine | 200ms |
| Problem card | Left border accent + title color shift | 200ms |
| Solution card | Left border accent + layer badge background fill | 200ms |
| Pricing card | Left border accent + tier name shift | 200ms |
| FAQ item | Left border accent + question text shift | 200ms |
| CTA button | Background lighten + translateY(-1px) + glow intensify | 150ms |

### Ambient animation budget

| Element | Type | Duration | Loop? | Where |
|---------|------|----------|-------|-------|
| Hero orbs (x3) | translate + scale | 8s | Yes, alternate | Hero only |
| Pipeline flow dots (x3) | translateX | 3s | Yes | Hero pipeline |
| Hero CTA glow pulse | box-shadow opacity | 2.5s | Yes | Hero CTA |
| Final CTA glow pulse | box-shadow opacity | 2.5s | Yes | Final CTA |
| Final CTA orbs (x3) | translate + scale | 8s | Yes, alternate | Final CTA |
| Scroll indicator bounce | translateY | 2s | Yes | Hero bottom |

Total looping: 10 in hero, 0 in middle, 3 in final CTA. Max concurrent visible: 10 (hero viewport).

### Reduced motion

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
  [data-animate] {
    opacity: 1 !important;
    transform: none !important;
  }
}
```

---

## 7. Section-by-Section Treatment

### 7.1 Hero

**Background:** #0a0b10 + three mesh gradient orbs (violet upper-left, cyan lower-right, deep-violet center-bottom). Grain overlay.

**Layout:** Centered, max-width 900px.

```
[Eyebrow: "AI-POWERED CODE QUALITY" — JetBrains Mono, 13px, violet]
[12px gap]
[Headline: Instrument Serif, 40-72px, white]
"Your AI writes the code."
"Who checks if it's right?" (← "right" = gradient text)
[24px gap]
[Subhead: Inter 18px, secondary]
"Multiple AI specialists review your code through quality gates
before it ships. You describe what you want in plain language."
[32px gap]
[CTAs: primary button + secondary ghost]
[12px gap]
[Friction: "Be first when we launch. No credit card needed."]
[96px gap]
[Pipeline visual: horizontal track, 3 gates (BUILD/ORGANIZE/POLISH)]
[Scroll indicator at bottom: chevron + "Scroll"]
```

Min-height: 100vh.

### 7.2 Problem ("The gaps AI tools leave open")

**Background:** #0f1018. 1px gradient divider at top.

**Layout:** Centered eyebrow + Instrument Serif headline, max-width 800px. Below: 2-column card grid, max-width 1000px.

4 problem cards, each with:
- Left-side SVG icon (24px, line-style, error/warning colors)
- Card title (Inter semibold)
- Card description (Inter regular, secondary)

Cards slide in from left (translateX(-32px)) with 80ms stagger.

### 7.3 Solution ("A team of AI specialists, working for you")

**Background:** #0a0b10. Faint radial glow at center (rgba(124,92,252,0.04)).

**Layout:** Centered eyebrow + headline + intro paragraph. Below: 3 horizontal layer cards connected by pipeline track (2px gradient line).

Each layer card:
- Layer badge ("L1"/"L2"/"L3" in JetBrains Mono, 28px pill, accent border)
- Layer name ("Build"/"Organize"/"Polish", Inter semibold)
- Description (Inter regular, secondary)

Pipeline gradient track appears here for the first time (B's narrative gradient approach). Flow dots optional.

### 7.4 How It Works (3 steps)

**Background:** #0f1018.

**Layout:** Centered headline. Three step cards horizontal, connected by dashed lines.

Each step:
- Circled number (48px, border accent, JetBrains Mono 20px)
- Title (Inter semibold)
- Description (Inter regular)

Step 1: "Describe what you want"
Step 2: "AI builds it with guardrails"
Step 3: "Ship with confidence"

### 7.5 Social Proof Strip

**Background:** #0a0b10.

Horizontal strip, max-width 1200px. 3-4 proof badges:
- "723" tests passing (JetBrains Mono, cyan)
- "52/52" requirements tracked
- Works with: Claude Code, Cursor, Windsurf

Framed by 1px top/bottom borders.

### 7.6 Features (Bento Grid)

**Background:** #0f1018.

Centered eyebrow + Instrument Serif headline. 6-column bento grid, 1400px max.

6 feature cards with C's editorial structure (eyebrow-title-body, NO icons):

Row 1 (wide cards):
1. "MULTI-MODEL" / "Multiple AIs, not just one" / description
2. "QUALITY GATES" / "Nothing ships without earning it" / description

Row 2 (narrow cards):
3. "TRACKING" / "Every requirement tracked" / description
4. "CLARITY" / "Ambiguity stops the line" / improved description from copy-improvements.md
5. "PERSISTENCE" / "Walk away and come back" / improved description

Row 3 (full width):
6. "CUSTOMIZATION" / "Your process, your rules" / improved description

### 7.7 Differentiator

**Background:** #13141e (feature background, warmer).

**Layout:** Centered editorial, max-width 800px.

Eyebrow: "WHAT MAKES US DIFFERENT"
Headline: Instrument Serif, "The difference is quality control"

Improved copy from copy-improvements.md:
"Other tools optimize for speed. Spec Manager optimizes for correctness.
Every function that reaches your branch has passed through multiple AI
reviewers, each checking different things. The code you get from other
tools went straight from one AI to your project with no inspection."

### 7.8 Pricing

**Background:** #0a0b10. Subtle radial glow behind pricing area.

Three pricing cards (Instrument Serif for prices):
- Free: $0 / runs local / full privacy / BYOK
- Hybrid: $15/mo / remote mgmt / easier setup
- Cloud: TBD / fully managed / future

CTA button below grid (not inside cards).

### 7.9 FAQ

**Background:** #0f1018.

Eyebrow: none. Headline: "Questions" (Instrument Serif, single word).

5 accordion items with C's left-border hover reveal.

Improved answers from copy-improvements.md.

### 7.10 Final CTA

**Background:** #0a0b10 + mesh gradient orbs at 60% intensity (bookend with hero).

Headline: Instrument Serif, "Ready to ship code you can trust?"
Subhead: "Your AI writes the code. Spec Manager checks if it's right."
Email form inline.
CTA button pulses.

### Footer

Minimal: brand name (gradient text) + copyright + built by.

---

## 8. Copy Improvements Applied

All copy from copy-improvements.md is applied:

1. "AI asks, not guesses" → "Ambiguity stops the line" with specific pipeline-halt description
2. Hero subhead: removed "No engineering degree required", replaced with "You describe what you want in plain language"
3. Differentiator body: broken parallel structure
4. Solution cards: all 3 rewritten to avoid triple-declarative patterns
5. Bento cards: "Your process, your rules" and "Walk away and come back" made concrete
6. FAQ answer 1: rewritten to avoid repeated "write and review"
7. Final CTA: removed redundant "Join the waitlist" sentence

---

## 9. Implementation Constraints

From phase6-constraints.md:
- LCP < 2.5s, INP < 200ms, CLS < 0.1
- Zero external JS libraries
- Total CSS < 50KB, Total JS < 10KB
- Pure CSS animations + vanilla JS IntersectionObserver
- All transforms use transform + opacity only
- prefers-reduced-motion support
- WCAG AA contrast at all text sizes
- Mobile-first (375px minimum, single column below 640px)
- No 3D, no video, no scrolljacking
