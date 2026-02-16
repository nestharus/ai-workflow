# Phase 6: Implementation Constraints

## Performance Budget (Core Web Vitals)

| Metric | Target | Implication |
|--------|--------|-------------|
| LCP | < 2.5s | Hero must render fast. No heavy JS blocking. Fonts preconnected. |
| INP | < 200ms | No scroll listeners on main thread. Use IntersectionObserver. |
| CLS | < 0.1 | Font swap strategy. Reserve space for images. No layout shifts from animations. |

### Font loading strategy
- Preconnect to Google Fonts (already in place)
- `display=swap` on font load (already set)
- Inter variable font reduces file count
- JetBrains Mono only loads 400 + 500 weights

### Animation performance
- All transforms use `transform` and `opacity` only (GPU-composited)
- No animating `width`, `height`, `margin`, `padding`, `top`, `left`
- IntersectionObserver for scroll triggers (no scroll event polling)
- Ambient loops use `will-change: transform` sparingly (max 3 elements)

### Asset budget
- Zero images in initial version (no product UI exists)
- SVG icons inline (no external requests)
- Total CSS < 50KB uncompressed
- Total JS < 10KB uncompressed
- No external JS libraries (no GSAP, no Three.js, no Spline)
  Pure CSS animations + vanilla JS IntersectionObserver only

## Mobile-First Constraints

- All layouts must work at 375px minimum
- Touch targets minimum 44px
- No hover-dependent content (hover enhances, never gates)
- Stacked single-column below 640px
- Font sizes already use clamp() for fluid scaling
- No horizontal scroll at any breakpoint

## Accessibility

- WCAG AA contrast minimum for all body text (4.5:1)
- WCAG AA for large text (3:1)
- `prefers-reduced-motion` support: all animations collapse to
  instant opacity:1, transform:none
- Keyboard navigation: all interactive elements focusable
- Focus ring visible (--focus-ring token)
- Semantic HTML: sections, articles, nav, headings in order
- ARIA labels on decorative/functional elements
- Form inputs labeled, status messages use aria-live

## What We Will NOT Build

Given no product UI and no external JS budget:
- No 3D hero (Spline) — performance risk, no product to show
- No video embeds — nothing to record
- No interactive demos — product doesn't exist yet
- No cursor-reactive effects — mobile-first constraint
- No scrolljacking — usability risk per NN/g

All visual interest must come from:
1. Typography (size, weight, spacing, color hierarchy)
2. Layout (grid, whitespace, composition)
3. CSS-only animation (transforms, opacity, scroll-triggered reveals)
4. Color and gradient (atmospheric depth, accent hierarchy)
5. Texture (grain overlay, surface differentiation)
