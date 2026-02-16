# Spec Manager -- Landing Page Design Tokens

**Date**: February 14, 2026
**Design Direction**: High-tech immersion + Scroll narrative product tour
**Brand Adjectives**: precise, confident, modern, intelligent, trustworthy
**Visual Metaphor**: Assembly line / Quality control pipeline -- code flows through illuminated gates

---

## Competitive Color Positioning

| Competitor | Palette                              |
|------------|--------------------------------------|
| Cursor     | Warm neutrals (#f7f7f4 / #14120b)   |
| Windsurf   | Teal on dark (#09B6A2)               |
| Bolt       | Light theme, glow cards              |
| Devin      | Dark/moody, atmospheric              |
| Replit     | Dark (#12141A), clean                |
| v0         | Light, minimal                       |

**Our position**: Deep indigo-black backgrounds with a violet-to-cyan accent gradient.
No one in the space owns violet. Cursor is warm, Windsurf is teal, Bolt is light,
Devin is moody-dark. A controlled violet accent on deep navy-black reads as
intelligent, precise, and premium -- distinct from every competitor.

---

## 1. Color Palette

```css
:root {
  /* ===== BACKGROUNDS ===== */
  /* Deep navy-black. Warmer than pure black, cooler than Devin's moody tones. */
  --bg-primary: #0a0b10;
  /* Slightly lifted for alternating sections. */
  --bg-secondary: #0f1018;

  /* ===== SURFACES ===== */
  /* Card backgrounds, modals, dropdowns. */
  --surface-1: #14151f;
  /* Elevated surface -- hovered cards, active states. */
  --surface-2: #1a1b28;
  /* Highest elevation -- tooltips, popovers. */
  --surface-3: #212333;

  /* ===== TEXT ===== */
  /* Primary text. Not pure white -- slightly warm for readability on dark. */
  --text-primary: #edeef2;
  /* Secondary text -- descriptions, supporting copy. */
  --text-secondary: #9496a8;
  /* Muted text -- captions, metadata, disabled states. */
  --text-muted: #5c5e72;

  /* ===== ACCENT ===== */
  /* Core brand violet. Distinctive from Windsurf's teal and Cursor's warm tones. */
  --accent: #7c5cfc;
  /* Lighter variant for hover states and highlights. */
  --accent-light: #9b82fd;
  /* Darker variant for pressed states. */
  --accent-dark: #5a3de8;
  /* Brand gradient -- violet to cyan. Evokes the "pipeline" metaphor:
     code entering (violet) and emerging verified (cyan). */
  --accent-gradient: linear-gradient(135deg, #7c5cfc 0%, #00d4ff 100%);
  /* Flatter gradient for large surfaces (hero backgrounds, section dividers). */
  --accent-gradient-subtle: linear-gradient(135deg, rgba(124, 92, 252, 0.15) 0%, rgba(0, 212, 255, 0.08) 100%);
  /* Horizontal pipeline gradient -- used for the quality gate flow visual. */
  --pipeline-gradient: linear-gradient(90deg, #7c5cfc 0%, #a78bfa 33%, #38bdf8 66%, #00d4ff 100%);

  /* ===== SEMANTIC ===== */
  /* Success -- quality gate passed, verification complete. */
  --success: #34d399;
  --success-muted: rgba(52, 211, 153, 0.15);
  /* Warning -- needs attention, demotion pending. */
  --warning: #fbbf24;
  --warning-muted: rgba(251, 191, 36, 0.15);
  /* Error -- gate failed, blocked. */
  --error: #f87171;
  --error-muted: rgba(248, 113, 113, 0.15);

  /* ===== BORDERS ===== */
  --border-subtle: rgba(255, 255, 255, 0.06);
  --border-default: rgba(255, 255, 255, 0.10);
  --border-strong: rgba(255, 255, 255, 0.16);
  --border-accent: rgba(124, 92, 252, 0.40);

  /* ===== GLOW COLORS ===== */
  /* CTA button halo -- violet glow, visible but not overwhelming. */
  --glow-cta: rgba(124, 92, 252, 0.45);
  --glow-cta-intense: rgba(124, 92, 252, 0.65);
  /* Quality gate glow -- cyan, representing verified/passed state. */
  --glow-gate: rgba(0, 212, 255, 0.40);
  --glow-gate-intense: rgba(0, 212, 255, 0.60);
  /* Success glow -- for checkmarks and passed indicators. */
  --glow-success: rgba(52, 211, 153, 0.40);
  /* Feature card hover glow -- subtle violet edge light. */
  --glow-card: rgba(124, 92, 252, 0.20);
  /* Pipeline node glow -- used for the assembly line dots/stages. */
  --glow-pipeline: rgba(167, 139, 250, 0.50);
}
```

---

## 2. Typography

### Font Stack

```css
:root {
  /* Headline font: Inter.
     Rationale: Geometric, modern, highly legible at all sizes. Variable font
     with optical sizing. The tight metrics and clean geometry convey precision
     without feeling cold. Used by Linear, Vercel, and other best-in-class
     developer tools -- familiar to the audience, signals quality.
     Alternative if more personality desired: "Plus Jakarta Sans" (rounder,
     friendlier, still modern). */
  --font-display: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;

  /* Body font: Same family for consistency. Inter's variable weight axis
     provides excellent contrast between headings and body without switching
     families. */
  --font-body: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;

  /* Mono font: JetBrains Mono.
     Rationale: Purpose-built for code. Ligatures make code snippets feel polished.
     Tall x-height improves readability at small sizes. Widely recognized by
     developers, lending credibility to any code shown on the page. */
  --font-mono: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Consolas', monospace;
}
```

### Type Scale

Based on a 1.250 ratio (Major Third) starting from 16px base. This produces
a scale that feels harmonious without the jumps being too dramatic -- important
for a page that mixes hero statements with explanatory body copy.

```css
:root {
  /* ===== FONT SIZES ===== */
  --text-hero: clamp(3rem, 5vw + 1rem, 4.5rem);      /* 48-72px -- hero headline only */
  --text-h1: clamp(2.25rem, 3vw + 0.75rem, 3rem);     /* 36-48px -- section headlines */
  --text-h2: clamp(1.75rem, 2vw + 0.5rem, 2.25rem);   /* 28-36px -- subsection headlines */
  --text-h3: clamp(1.25rem, 1.5vw + 0.25rem, 1.5rem); /* 20-24px -- card titles */
  --text-h4: 1.125rem;                                  /* 18px -- labels, eyebrow text */
  --text-body: 1rem;                                     /* 16px -- body copy */
  --text-body-lg: 1.125rem;                              /* 18px -- lead paragraphs, hero subhead */
  --text-small: 0.875rem;                                /* 14px -- secondary info */
  --text-caption: 0.75rem;                               /* 12px -- metadata, fine print */

  /* ===== FONT WEIGHTS ===== */
  --weight-regular: 400;
  --weight-medium: 500;
  --weight-semibold: 600;
  --weight-bold: 700;

  /* ===== LINE HEIGHTS ===== */
  --leading-tight: 1.1;      /* Hero headlines */
  --leading-snug: 1.25;      /* Section headlines */
  --leading-normal: 1.5;     /* Body text, descriptions */
  --leading-relaxed: 1.625;  /* Long-form reading */

  /* ===== LETTER SPACING ===== */
  --tracking-tighter: -0.03em;  /* Hero text -- pull in for visual density */
  --tracking-tight: -0.02em;    /* Section headlines */
  --tracking-normal: 0em;       /* Body text */
  --tracking-wide: 0.04em;      /* Eyebrow labels, small caps, CTAs */
  --tracking-wider: 0.08em;     /* Overline/eyebrow text above section headlines */
}
```

### Usage Guidelines

| Element           | Size          | Weight     | Leading        | Tracking        |
|-------------------|---------------|------------|----------------|-----------------|
| Hero headline     | `--text-hero` | `--weight-bold` | `--leading-tight` | `--tracking-tighter` |
| Hero subhead      | `--text-body-lg` | `--weight-regular` | `--leading-normal` | `--tracking-normal` |
| Eyebrow labels    | `--text-caption` | `--weight-semibold` | `--leading-normal` | `--tracking-wider` |
| Section headline  | `--text-h1`  | `--weight-bold` | `--leading-snug` | `--tracking-tight` |
| Subsection head   | `--text-h2`  | `--weight-semibold` | `--leading-snug` | `--tracking-tight` |
| Card title        | `--text-h3`  | `--weight-semibold` | `--leading-snug` | `--tracking-normal` |
| Body copy         | `--text-body` | `--weight-regular` | `--leading-relaxed` | `--tracking-normal` |
| Button label      | `--text-small` | `--weight-semibold` | `--leading-normal` | `--tracking-wide` |
| Caption/metadata  | `--text-caption` | `--weight-medium` | `--leading-normal` | `--tracking-wide` |
| Code inline       | `--text-small` | `--weight-regular` | `--leading-normal` | `--tracking-normal` |

---

## 3. Shape System

```css
:root {
  /* ===== BORDER RADIUS ===== */
  --radius-sm: 6px;     /* Small elements: tags, badges, inline code blocks */
  --radius-md: 10px;    /* Buttons, inputs, small cards */
  --radius-lg: 16px;    /* Feature cards, bento grid items */
  --radius-xl: 24px;    /* Hero cards, modal dialogs, large containers */
  --radius-full: 9999px; /* Pills, avatar circles, toggle tracks */

  /* ===== BORDER WIDTHS ===== */
  --border-thin: 1px;
  --border-medium: 1.5px;
  --border-thick: 2px;
}
```

### Card Presets

```css
/* --- Base card --- */
/* Used for bento grid items, feature cards. */
.card {
  background: var(--surface-1);
  border: var(--border-thin) solid var(--border-subtle);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-md);
}

/* --- Elevated card (hovered) --- */
/* Hover state for interactive cards. Border brightens, subtle glow appears. */
.card:hover {
  background: var(--surface-2);
  border-color: var(--border-accent);
  box-shadow: var(--shadow-lg), var(--glow-card-shadow);
}

/* --- Glass card --- */
/* For overlaid elements on gradient backgrounds (e.g., pricing cards on hero). */
.card-glass {
  background: rgba(20, 21, 31, 0.60);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: var(--border-thin) solid var(--border-default);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-md);
}

/* --- Pipeline card --- */
/* For quality gate stages in the workflow visual. Glowing border on the active gate. */
.card-pipeline {
  background: var(--surface-1);
  border: var(--border-medium) solid var(--border-subtle);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
}

.card-pipeline.active {
  border-color: var(--accent);
  box-shadow: var(--glow-gate-shadow);
}
```

---

## 4. Motion Tokens

```css
:root {
  /* ===== DURATIONS ===== */
  --duration-fast: 150ms;     /* Micro-interactions: hover color, focus ring */
  --duration-standard: 250ms; /* Standard transitions: card hover, button state */
  --duration-slow: 400ms;     /* Emphasis transitions: modal open, panel slide */
  --duration-glacial: 600ms;  /* Scroll-triggered entrances, hero animations */

  /* ===== EASING CURVES ===== */
  /* Standard -- for most transitions. Starts fast, decelerates naturally. */
  --ease-standard: cubic-bezier(0.25, 0.1, 0.25, 1.0);
  /* Decelerate -- for elements entering the viewport. Starts with momentum,
     settles into place. Used for scroll-triggered card reveals. */
  --ease-decel: cubic-bezier(0.0, 0.0, 0.2, 1.0);
  /* Accelerate -- for elements exiting. Picks up speed as it leaves. */
  --ease-accel: cubic-bezier(0.4, 0.0, 1.0, 1.0);
  /* Spring -- for playful interactions. Slight overshoot and settle.
     Used sparingly: CTA button press, success checkmarks. */
  --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1.0);
  /* Linear -- for continuous animations (progress bars, loading). */
  --ease-linear: linear;
}
```

### Scroll Animation Guidelines

All scroll-driven animations use the Intersection Observer API (or CSS
`animation-timeline: scroll()` where supported). No JavaScript scroll
listeners polling on every frame.

| Element               | Animation                          | Trigger     | Duration          | Easing          |
|-----------------------|------------------------------------|-------------|-------------------|-----------------|
| Section headline      | Fade up 24px + opacity 0 to 1      | 15% visible | `--duration-glacial` | `--ease-decel` |
| Body text             | Fade up 16px + opacity 0 to 1      | 15% visible | `--duration-slow`    | `--ease-decel` |
| Bento card            | Fade up 32px + scale(0.97) to 1    | 20% visible | `--duration-glacial` | `--ease-decel` |
| Pipeline gate         | Scale(0.9) to 1 + glow pulse       | 30% visible | `--duration-glacial` | `--ease-spring` |
| Problem card (reveal) | Slide in from left 48px + opacity   | 20% visible | `--duration-slow`    | `--ease-decel` |
| CTA button            | No scroll animation (always visible)| --          | --                   | --              |

**Stagger pattern**: When multiple cards enter together (bento grid), stagger
each by 80ms. Maximum stagger group: 6 items. Beyond that, animate all at once.

### Ambient Animations (Always Running)

| Element             | Animation                        | Duration | Easing           |
|---------------------|----------------------------------|----------|------------------|
| Hero glow orb       | Slow drift (translate + scale)   | 8s loop  | `--ease-linear`  |
| Pipeline flow dots  | Travel along path                | 3s loop  | `--ease-linear`  |
| CTA button glow     | Gentle pulse (opacity 0.3-0.6)   | 2.5s loop| `--ease-standard`|
| Gate checkmark      | Pop in (scale 0 to 1 with spring)| 400ms    | `--ease-spring`  |

### Reduced Motion

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

  /* Elements that rely on scroll-triggered fade-in should be
     immediately visible with no transform. */
  [data-animate] {
    opacity: 1 !important;
    transform: none !important;
  }
}
```

---

## 5. Spacing Scale

4px base unit. Every spacing value is a multiple of 4.

```css
:root {
  --space-1: 0.25rem;   /* 4px -- tight internal padding, icon gaps */
  --space-2: 0.5rem;    /* 8px -- small gaps, inline spacing */
  --space-3: 0.75rem;   /* 12px -- compact card padding, input padding */
  --space-4: 1rem;      /* 16px -- standard gap, paragraph margin */
  --space-5: 1.5rem;    /* 24px -- card internal padding */
  --space-6: 2rem;      /* 32px -- between card groups */
  --space-7: 2.5rem;    /* 40px -- between content blocks within a section */
  --space-8: 3rem;      /* 48px -- section internal padding (top/bottom) */
  --space-9: 4rem;      /* 64px -- between major sections */
  --space-10: 5rem;     /* 80px -- hero vertical padding */
  --space-11: 6rem;     /* 96px -- large section spacing */
  --space-12: 8rem;     /* 128px -- hero top padding, major visual breaks */

  /* ===== LAYOUT TOKENS ===== */
  --content-max-width: 1200px;   /* Main content container */
  --content-narrow: 800px;       /* Text-heavy sections (problem, FAQ) */
  --content-wide: 1400px;        /* Full-bleed bento grid */
  --gutter: var(--space-4);      /* Default grid gap at mobile */
  --gutter-lg: var(--space-6);   /* Grid gap at desktop */
}
```

---

## 6. Shadow and Glow System

```css
:root {
  /* ===== ELEVATION SHADOWS ===== */
  /* Layered shadows for depth. Each level adds perceived distance from surface. */

  /* Level 1 -- Resting cards, subtle lift. */
  --shadow-sm:
    0 1px 2px rgba(0, 0, 0, 0.30),
    0 1px 3px rgba(0, 0, 0, 0.15);

  /* Level 2 -- Hovered cards, interactive elements. */
  --shadow-md:
    0 4px 6px rgba(0, 0, 0, 0.25),
    0 2px 4px rgba(0, 0, 0, 0.20);

  /* Level 3 -- Modals, dropdowns, floating elements. */
  --shadow-lg:
    0 10px 25px rgba(0, 0, 0, 0.35),
    0 4px 10px rgba(0, 0, 0, 0.20);

  /* Level 4 -- Hero visual, major floating containers. */
  --shadow-xl:
    0 20px 50px rgba(0, 0, 0, 0.40),
    0 8px 20px rgba(0, 0, 0, 0.25);

  /* ===== GLOW PRESETS ===== */

  /* CTA button glow -- visible halo behind primary buttons.
     Two layers: tight inner glow + diffuse outer glow. */
  --glow-cta-shadow:
    0 0 20px var(--glow-cta),
    0 0 60px rgba(124, 92, 252, 0.20);

  /* CTA button glow on hover -- intensified. */
  --glow-cta-shadow-hover:
    0 0 25px var(--glow-cta-intense),
    0 0 80px rgba(124, 92, 252, 0.30);

  /* Quality gate glow -- cyan halo around pipeline stages.
     Used when a gate is "active" or "passed." */
  --glow-gate-shadow:
    0 0 15px var(--glow-gate),
    0 0 45px rgba(0, 212, 255, 0.15);

  /* Quality gate glow -- intensified for the currently-active stage. */
  --glow-gate-shadow-active:
    0 0 20px var(--glow-gate-intense),
    0 0 60px rgba(0, 212, 255, 0.25);

  /* Success checkmark glow -- green halo behind passed indicators. */
  --glow-success-shadow:
    0 0 12px var(--glow-success),
    0 0 30px rgba(52, 211, 153, 0.15);

  /* Feature card hover glow -- subtle violet edge light.
     Appears as a soft halo behind the card on hover. */
  --glow-card-shadow:
    0 0 30px var(--glow-card),
    0 4px 15px rgba(0, 0, 0, 0.30);

  /* Pipeline node glow -- for the small dots/circles along the pipeline visual. */
  --glow-pipeline-shadow:
    0 0 10px var(--glow-pipeline),
    0 0 25px rgba(167, 139, 250, 0.20);

  /* Text glow -- for the hero headline accent word or counter numbers. */
  --glow-text:
    0 0 40px rgba(124, 92, 252, 0.30),
    0 0 80px rgba(124, 92, 252, 0.10);
}
```

### Usage Map

| Element                       | Shadow / Glow Token              |
|-------------------------------|----------------------------------|
| Resting bento card            | `--shadow-sm`                    |
| Hovered bento card            | `--shadow-lg` + `--glow-card-shadow` |
| CTA button (resting)          | `--glow-cta-shadow`              |
| CTA button (hovered)          | `--glow-cta-shadow-hover`        |
| Pipeline gate (inactive)      | `--shadow-sm`                    |
| Pipeline gate (active)        | `--glow-gate-shadow-active`      |
| Pipeline gate (passed)        | `--glow-gate-shadow` + `--glow-success-shadow` |
| Pipeline flow dot             | `--glow-pipeline-shadow`         |
| Pricing card                  | `--shadow-md`                    |
| Modal / dialog                | `--shadow-xl`                    |
| Hero headline accent word     | `--glow-text` (as text-shadow)   |

---

## 7. Ambient Effects

### Noise/Grain Overlay

A subtle film-grain texture adds depth and tactility to the dark surfaces,
preventing the "flat digital" feeling. Applied as a fixed pseudo-element
covering the entire page.

```css
/* Grain texture -- applied to the page body via ::after. */
.grain-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  pointer-events: none;
  opacity: 0.030;             /* Very subtle -- just enough to feel, not see. */
  mix-blend-mode: overlay;
  background-image: url("data:image/svg+xml,..."); /* Inline noise SVG or generated via canvas. */
  /* Production: use a 200x200 noise tile PNG at ~2KB, repeated. */
  background-repeat: repeat;
  background-size: 200px 200px;
}

/* OR use CSS filter on a transparent overlay: */
.grain-overlay-alt::after {
  content: '';
  position: fixed;
  inset: 0;
  z-index: 9999;
  pointer-events: none;
  opacity: 0.035;
  filter: url(#noise);  /* SVG feTurbulence filter */
  mix-blend-mode: overlay;
}
```

**SVG noise filter definition** (place in the HTML once):
```html
<svg width="0" height="0" style="position:absolute">
  <filter id="noise">
    <feTurbulence type="fractalNoise" baseFrequency="0.65" numOctaves="3" stitchTiles="stitch"/>
    <feColorMatrix type="saturate" values="0"/>
  </filter>
</svg>
```

### Gradient Presets

```css
:root {
  /* Hero background -- large radial glow behind the hero section.
     Creates the "lit from within" feeling. Position: center, slightly above midpoint. */
  --gradient-hero-glow: radial-gradient(
    ellipse 80% 50% at 50% 40%,
    rgba(124, 92, 252, 0.12) 0%,
    rgba(0, 212, 255, 0.04) 40%,
    transparent 70%
  );

  /* Section divider -- horizontal gradient fade used between major sections. */
  --gradient-section-divider: linear-gradient(
    90deg,
    transparent 0%,
    var(--border-subtle) 20%,
    var(--border-default) 50%,
    var(--border-subtle) 80%,
    transparent 100%
  );

  /* Pipeline background -- the track behind the quality gate flow visual.
     Subtle horizontal gradient suggesting direction (left to right = progress). */
  --gradient-pipeline-track: linear-gradient(
    90deg,
    rgba(124, 92, 252, 0.06) 0%,
    rgba(167, 139, 250, 0.04) 50%,
    rgba(0, 212, 255, 0.06) 100%
  );

  /* Card shine -- a diagonal highlight for glass cards on hover.
     Mimics light reflection. Applied as a pseudo-element. */
  --gradient-card-shine: linear-gradient(
    135deg,
    rgba(255, 255, 255, 0.04) 0%,
    transparent 50%,
    transparent 100%
  );

  /* Mesh gradient -- for the hero section background. Layer multiple
     radial gradients to create depth. */
  --gradient-mesh-violet: radial-gradient(
    circle at 20% 30%,
    rgba(124, 92, 252, 0.10) 0%,
    transparent 50%
  );
  --gradient-mesh-cyan: radial-gradient(
    circle at 80% 60%,
    rgba(0, 212, 255, 0.06) 0%,
    transparent 50%
  );
  --gradient-mesh-deep: radial-gradient(
    circle at 50% 80%,
    rgba(90, 61, 232, 0.08) 0%,
    transparent 40%
  );
}
```

### Glow Intensity Guidelines

Glow intensity should be controlled and purposeful. Overuse destroys the effect.

| Context                  | Intensity Level | Notes                                  |
|--------------------------|-----------------|----------------------------------------|
| Hero background          | Low (opacity 0.06-0.12) | Atmospheric. Should not compete with text. |
| CTA button resting       | Medium (opacity 0.20-0.45) | Visible halo. Primary attention driver. |
| CTA button hovered       | High (opacity 0.30-0.65) | Intensified. Clear interactive feedback. |
| Pipeline gate (inactive) | None            | Dormant gates have no glow.            |
| Pipeline gate (active)   | Medium-High (opacity 0.25-0.60) | The "illuminated gate" metaphor. |
| Pipeline gate (passed)   | Medium (opacity 0.15-0.40) | Settled glow. Gate has done its work. |
| Feature card hover       | Low (opacity 0.10-0.20) | Whisper of light. Should not distract from content. |
| Success checkmark        | Medium (opacity 0.15-0.40) | Brief pulse on appearance, then settle. |
| Text glow (hero accent)  | Low (opacity 0.10-0.30) | Applied as text-shadow. Legibility first. |

**Rule of thumb**: At any given moment, no more than 2-3 glowing elements should
be visible in the viewport. If everything glows, nothing glows.

---

## 8. Component Token Presets

Quick-reference tokens for the most common components.

### Primary CTA Button

```css
.btn-primary {
  /* Layout */
  padding: var(--space-3) var(--space-6);
  border-radius: var(--radius-md);
  border: none;

  /* Color */
  background: var(--accent);
  color: #ffffff;
  box-shadow: var(--glow-cta-shadow);

  /* Typography */
  font-family: var(--font-body);
  font-size: var(--text-small);
  font-weight: var(--weight-semibold);
  letter-spacing: var(--tracking-wide);

  /* Interaction */
  cursor: pointer;
  transition:
    background var(--duration-fast) var(--ease-standard),
    box-shadow var(--duration-standard) var(--ease-standard),
    transform var(--duration-fast) var(--ease-standard);
}

.btn-primary:hover {
  background: var(--accent-light);
  box-shadow: var(--glow-cta-shadow-hover);
  transform: translateY(-1px);
}

.btn-primary:active {
  background: var(--accent-dark);
  box-shadow: var(--glow-cta-shadow);
  transform: translateY(0);
}
```

### Secondary Button (Ghost)

```css
.btn-secondary {
  padding: var(--space-3) var(--space-6);
  border-radius: var(--radius-md);
  border: var(--border-thin) solid var(--border-strong);
  background: transparent;
  color: var(--text-primary);
  font-family: var(--font-body);
  font-size: var(--text-small);
  font-weight: var(--weight-semibold);
  letter-spacing: var(--tracking-wide);
  cursor: pointer;
  transition:
    border-color var(--duration-fast) var(--ease-standard),
    background var(--duration-fast) var(--ease-standard);
}

.btn-secondary:hover {
  border-color: var(--accent);
  background: rgba(124, 92, 252, 0.08);
}
```

### Email Input (Waitlist)

```css
.input-email {
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  border: var(--border-thin) solid var(--border-default);
  background: var(--surface-1);
  color: var(--text-primary);
  font-family: var(--font-body);
  font-size: var(--text-body);
  transition:
    border-color var(--duration-fast) var(--ease-standard),
    box-shadow var(--duration-fast) var(--ease-standard);
}

.input-email:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(124, 92, 252, 0.20);
}

.input-email::placeholder {
  color: var(--text-muted);
}
```

### Bento Grid

```css
.bento-grid {
  display: grid;
  gap: var(--gutter-lg);
  max-width: var(--content-wide);
  margin: 0 auto;
  padding: 0 var(--space-4);
  /* 6-column grid at desktop. Cards span 2 or 3 columns.
     At tablet: 4 columns. At mobile: 1 column. */
  grid-template-columns: repeat(6, 1fr);
}

@media (max-width: 1024px) {
  .bento-grid {
    grid-template-columns: repeat(4, 1fr);
  }
}

@media (max-width: 640px) {
  .bento-grid {
    grid-template-columns: 1fr;
    gap: var(--gutter);
  }
}
```

---

## 9. Breakpoints

```css
:root {
  /* Reference only -- use in @media queries, not as custom properties. */
  /* --bp-sm: 640px;   Mobile landscape / small tablet */
  /* --bp-md: 768px;   Tablet portrait */
  /* --bp-lg: 1024px;  Tablet landscape / small desktop */
  /* --bp-xl: 1280px;  Desktop */
  /* --bp-2xl: 1536px; Large desktop */
}
```

---

## 10. Accessibility Tokens

```css
:root {
  /* Focus ring -- visible, high contrast, does not depend on color alone. */
  --focus-ring: 0 0 0 2px var(--bg-primary), 0 0 0 4px var(--accent);
  /* Minimum touch target (WCAG 2.2 Level AA). */
  --min-touch-target: 44px;
}
```

All text-on-background combinations must meet WCAG AA contrast ratios:

| Combination                         | Ratio  | Passes |
|-------------------------------------|--------|--------|
| `--text-primary` on `--bg-primary`  | 15.2:1 | AAA    |
| `--text-secondary` on `--bg-primary`| 5.8:1  | AA     |
| `--text-muted` on `--bg-primary`    | 3.2:1  | Fails body text, OK for large text only |
| `--accent` on `--bg-primary`        | 4.8:1  | AA (large text); use `--accent-light` for small text |
| `#ffffff` on `--accent`             | 4.6:1  | AA (large text); acceptable for buttons |
| `--success` on `--bg-primary`       | 9.1:1  | AAA    |
| `--error` on `--bg-primary`         | 5.4:1  | AA     |

**Note**: `--text-muted` must only be used for non-essential information or
decorative text at sizes >= 18px. For essential content at small sizes, use
`--text-secondary` minimum.

---

## 11. Google Fonts Import

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
```

Load only the weights specified above. Inter's optical sizing (`opsz`) axis
is included for automatic adjustment at different sizes. JetBrains Mono only
needs Regular and Medium for inline code and code blocks.

---

## Design Token Summary

| Category        | Count | Key Decisions                                   |
|-----------------|-------|-------------------------------------------------|
| Colors          | 30+   | Violet-cyan on deep navy-black (unique in market)|
| Typography      | 3 families, 9 sizes | Inter + JetBrains Mono, Major Third scale |
| Spacing         | 12 steps | 4px base, rem units                         |
| Radii           | 5 levels | 6px-pill range                              |
| Shadows         | 4 elevations | Dark-optimized, layered                 |
| Glows           | 7 presets | CTA, gate, success, card, pipeline, text   |
| Motion          | 4 durations, 5 curves | Scroll-driven + ambient loops       |
| Gradients       | 6 presets | Hero mesh, pipeline track, card shine      |
