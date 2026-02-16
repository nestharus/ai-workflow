## A companion system to the landing page: “Reality → Brand → Assets → Page → Variants”

The landing page is the *output*. The missing piece is a machine-readable “marketing truth + brand kit + asset manifest” layer that can be generated (mostly) from autonomous product exploration, then used to assemble pages, videos, and variants without the telephone game.

This is an implementation-oriented article/spec you can treat like an internal doc.

---

# 1) The core artifact: a single “Marketing Source of Truth” file

### Why

To automate landing pages, you need *one canonical file* that everything reads from:

* landing page copy
* layout/module selection
* design tokens and brand assets
* video scripts and renders
* variant generation + routing rules
* truth/claim validation

### What it is

A structured bundle (JSON/YAML) made of six sub-documents:

1. **Product Reality Map** (truth layer)
2. **Strategic Source File** (positioning layer)
3. **Brand Kit** (company + product sub-brand)
4. **Asset Manifest** (what to capture/generate + specs)
5. **Page Recipe** (modules + narrative)
6. **Video Recipe** (Remotion compositions + data props)

The output is comparable to “design tokens for marketing,” except it includes narrative and evidence, not just colors/fonts.

---

# 2) Product Reality Map: autonomous product exploration + evidence ledger

Your stated premise is correct: “absolute truth” comes from (a) source code and (b) user behavior.

### 2.1 Extraction strategies that actually work in practice

#### A) Code surface extraction (what exists, constraints, guarantees)

Outputs:

* feature inventory (IDs, descriptions, UI entry points)
* constraints (latency, limitations, plan gating, permissions)
* “proofable claims” candidates (benchmarks, scaling, reliability)

If you use a deep reasoning model for this, note Gemini 3 Deep Think is positioned as a specialized reasoning mode aimed at hard science/engineering problems; you can map that capability to “technical truth extraction” tasks. ([blog.google][1])

#### B) UI surface extraction (what users can see)

Two automation-friendly sources:

* **Storybook snapshots**: Every story becomes a renderable “state,” and visual tests can snapshot stories at scale. ([Storybook][2])
* **Chromatic** can capture and diff Storybook visuals across environments (useful as a stable pipeline for generating consistent UI screenshots). ([Storybook][2])

Practical use: treat Storybook as a deterministic “UI state generator” for marketing assets (feature cards, UI montages, micro-demos).

#### C) Runtime exploration (what actually happens)

Use browser automation to:

* traverse golden paths
* capture screenshots
* record videos of flows
* collect network logs (optional)
* collect timings (optional)

Playwright can record videos in tests and persists them after browser context closure; it’s reliable for automated flow capture. ([Playwright][3])

#### D) Behavioral truth (where users struggle + what matters)

For landing-page automation, you want:

* friction patterns (rage clicks, dead clicks, drop-offs)
* “moment of value” time
* top tasks by frequency
* objections inferred from support logs

Microsoft Clarity provides session recordings and heatmaps and emphasizes turning behavior into insights (including “rage taps/clicks” and aggregated interaction visualization). ([Microsoft Clarity][4])

#### E) Pre-launch “design sanity checks” (predictive)

Two use cases:

* verify hierarchy before running traffic (CTA visibility, attention distribution)
* compare layout variants before building everything

Clarity’s Predictive Heatmaps are described as showing how a typical user may interact with a site from a URL or image, and their blog frames this as forecasting likely clicks/scroll/attention using AI/ML. ([Microsoft Clarity][5])
Attention Insight claims predictive eye-tracking heatmaps “up to 96% accurate” (vendor claim) and explains its method as trained on eye-tracking datasets. ([Attention Insight][6])
Balance: predictive models have limitations; Tobii explicitly discusses challenges/limits of predictive models vs real eye tracking in some contexts. ([tobii.com][7])

### 2.2 The “evidence ledger” (this is what kills the telephone game)

Every marketing claim must map to evidence:

* code references
* telemetry metrics
* user behavior patterns
* reproducible benchmark scripts
* legal/plan constraints

**Rule:** if a claim can’t be evidenced, it can’t appear as a hard fact on the landing page. It can appear only as “positioning language” (soft claim), or be removed.

### 2.3 Minimal schema for Product Reality Map (example)

```json
{
  "product": { "name": "Acme", "repo": "github.com/org/acme" },
  "features": [
    {
      "id": "export_csv",
      "ui_entrypoints": ["Reports > Export", "Dashboard > Share"],
      "what_it_does": "Exports filtered reports to CSV",
      "constraints": {
        "plan": "Pro+",
        "permissions": ["reports:read"],
        "latency_budget_ms": { "p50": 400, "p95": 900 }
      },
      "behavioral_truth": {
        "session_patterns": ["rage_click_loading_state_missing"],
        "top_user_emotion": "anxiety",
        "why": "Export feels stuck; no progress feedback"
      },
      "evidence": {
        "code_refs": ["src/features/export/export_csv.ts"],
        "telemetry": ["event:export_clicked", "metric:export_duration_ms"],
        "support_refs": ["ticket_tag:export_slow", "ticket_tag:export_failed"]
      }
    }
  ]
}
```

---

# 3) Strategic Source File: turning features into narratives (without lying)

This file translates the Reality Map into:

* personas + jobs-to-be-done angles
* value prop stack (category, outcome, differentiator)
* objections + answers (grounded in truth)
* tone-of-voice constraints
* CTA strategy
* variant plan (segments and what differs)

### 3.1 The “truth-preserving transformation”

For each feature:

* **Mechanism** (what code actually does)
* **User outcome** (what it enables)
* **Emotional relief** (what pain it removes)
* **Proof** (what you can show)
* **Boundary** (what you must not claim)

### 3.2 Strategic schema (example)

```json
{
  "positioning": {
    "category": "Reporting automation",
    "primary_outcome": "Faster exports, fewer failures",
    "differentiator": "Compression + streaming pipeline"
  },
  "personas": [
    {
      "id": "data_analyst_deadline",
      "primary_pain": "waiting + uncertainty",
      "headline_angle": "Get reports out instantly",
      "proof_to_show": ["before/after flow", "latency percentiles"]
    }
  ],
  "claims": [
    {
      "claim": "Exports feel instant with visible progress",
      "type": "functional",
      "allowed_channels": ["landing", "video"],
      "evidence_refs": ["telemetry:export_duration_ms", "ux:progress_indicator_added"]
    }
  ],
  "objections": [
    { "id": "does_it_work_with_x", "answer": "Supports X via integration Y", "evidence_refs": ["docs:integrations"] }
  ]
}
```

---

# 4) Brand Kit: company brand + product sub-brand, encoded as tokens + assets

You explicitly need two layers:

* **Company brand** (trust, credibility, portfolio coherence)
* **Product brand** (feature story, audience resonance)

### 4.1 Choose brand architecture first (it dictates how many assets you need)

Common models:

* **Branded house**: everything shares the master brand’s name/look/values. ([Qualtrics][8])
* **Endorsed brands**: product brands have their own identity but borrow legitimacy from the parent brand. ([Qualtrics][8])
* **House of brands**: products operate independently with distinct identities. ([Qualtrics][8])

**Automation implication:**
Branded house → fewer unique assets per product, more reuse.
House of brands → many assets per product, higher generation cost.

### 4.2 Encode the Brand Kit as design tokens (portable + automatable)

Use the Design Tokens Community Group (DTCG) format so tokens can move across tools/platforms. The spec explicitly defines a file format to exchange design tokens between tools. ([Design Tokens][9])

**Brand tokens you actually need for landing pages**

* color roles (bg/surface/text/accent/semantic)
* type scale + font families
* spacing scale
* radii
* borders
* shadows + elevation model
* motion tokens (durations/easing)
* “ambience tokens” (noise strength, glow intensity, gradient presets)

Minimal DTCG-ish sample:

```json
{
  "color": {
    "bg": { "$value": "#0B0F19", "$type": "color" },
    "surface": { "$value": "#111827", "$type": "color" },
    "accent": { "$value": "#7C3AED", "$type": "color" }
  },
  "radius": {
    "card": { "$value": "16px", "$type": "dimension" },
    "button": { "$value": "999px", "$type": "dimension" }
  }
}
```

### 4.3 Logo asset requirements (keep it minimal, but complete)

For **company**:

* wordmark (light/dark)
* symbol (light/dark)
* favicon (16/32)
* social preview lockup (OG)
* app icon (if applicable)

For **product**:

* product symbol (or endorsed lockup)
* product wordmark (optional)
* “product badge” version for feature callouts

Automation note: generate *candidates* in an art pipeline, but finalize as vectors with rules that survive all contexts (tiny sizes, monochrome, inversion).

---

# 5) Icon system pipeline (critical because it impacts perceived polish)

If your landing pages are modular (bento cards), icons become structural—not decorative.

### 5.1 Pick one icon style family, then lock rules

**Material Symbols** are available in three styles (outlined, rounded, sharp). ([Material Design][10])
**SF Symbols** supports multiple rendering modes (monochrome, hierarchical, palette, multicolor). ([Apple Developer][11])
**Lucide** positions itself as “clean & consistent” with strict design rules; its guide specifies constraints like a 24×24 canvas, padding, and stroke width rules. ([Lucide][12])

### 5.2 Rules to encode (so icons can be generated + validated)

* grid size (e.g., 24px)
* live area (padding)
* stroke width
* line caps + joins
* corner radius policy
* filled vs outline policy

Adobe’s icon guidance notes outline vs filled as a major stylistic decision and ties filled/duotone to emphasis and dark backgrounds. ([adobe.design][13])

### 5.3 Practical automation tactic: “icon linting”

Once you encode geometry rules, you can build an automated validator:

* rejects icons with inconsistent strokes/radii
* warns on shapes that don’t align to grid
* flags filled regions that break style

This prevents “generated icons drift.”

---

# 6) Ambience pipeline (backgrounds, lighting, atmosphere) without becoming heavy

Your constraint is right: minor art assets can get heavy. The job is to make ambience *token-driven* and lightweight.

### 6.1 Tokenize ambience rather than shipping giant images

* gradient presets (mesh/linear/radial)
* noise overlay intensity + scale
* glow intensity + blur radius
* shadow model (soft realism vs crisp)
* “material” presets (glass blur vs opaque surfaces)

### 6.2 Ambient storytelling by category

* AI/devtools: darker bases + glow accents + technical texture
* consumer: brighter bases + friendly shapes + softer shadows
* enterprise: restrained palette + high readability + conservative motion

Ambience should never compete with product screenshots or the CTA hierarchy.

---

# 7) Asset Manifest: the contract between exploration and creative pipelines

This is where automation becomes real: you don’t “hope” you have assets; you *specify* them.

### 7.1 Asset Manifest structure

Each asset is a job with:

* purpose (hero proof, feature demo, testimonial proof, etc.)
* spec (format, dims, max bytes, duration)
* source strategy (storybook snapshot, playwright capture, manual upload, art pipeline)
* fallback (if capture fails)
* compliance (alt text, privacy masking, claim ties)

Example:

```json
{
  "assets": [
    {
      "id": "hero_demo_video",
      "purpose": "Show the core flow in <8s",
      "type": "video",
      "spec": { "aspect": "16:9", "max_seconds": 8, "max_mb": 8 },
      "source": "playwright_recording",
      "capture": { "route": "login > reports > export", "mask_selectors": ["[data-pii]"] },
      "fallback": "storybook_animation_montage"
    }
  ]
}
```

### 7.2 Capture strategies (automatable)

* Storybook → deterministic component + state snapshots ([Storybook][2])
* Playwright → end-to-end flow video capture ([Playwright][3])
* Clarity → real user behavior patterns (not assets, but insight inputs) ([Microsoft Clarity][4])

---

# 8) Video Recipe: Remotion as the render engine for marketing video variants

Remotion’s core value here: **videos are code + props**.

Remotion describes itself as creating real MP4 videos with React. ([Remotion][14])
Key features relevant to automation:

* **Parameterized videos**: ingest/validate/edit data used to parametrize content and metadata; supports input props + dynamic metadata via `calculateMetadata()`. ([Remotion][15])
* **Batch rendering from datasets**: render many videos from JSON datasets. ([Remotion][16])
* **Programmatic rendering**: `renderMedia()` renders video/audio. ([Remotion][17])
* **Frame/still extraction**: `renderStill()` renders a single frame to an image (useful for hero posters). ([Remotion][18])
* **Web rendering exists but is explicitly “very experimental.”** ([Remotion][19])
* Remotion Studio can be deployed for non-technical teammates to render via a URL workflow. ([Remotion][20])

### 8.1 How to structure Remotion for marketing automation

Make your marketing video system a component library:

* `IntroHook(props)`
* `ProblemScene(props)`
* `MechanismScene(props)` (diagram + metric)
* `DemoScene(props)` (screen capture + callouts)
* `ProofScene(props)` (logos/testimonial)
* `CTAEndCard(props)`

Then the **Video Recipe** selects scenes + timing tokens based on persona + narrative.

### 8.2 Remotion “variant factory” pattern

* Input: Strategic Source File + Asset Manifest
* Output: N variants (persona × channel × length)
* Render: dataset render (JSON rows) ([Remotion][16])
* Validate: props schema and guardrails (no unsupported claims)

---

# 9) Page Recipe: automated landing page assembly from a module library

### 9.1 Module library (the reusable building blocks)

Each module has:

* required inputs (copy fields + assets)
* optional inputs
* constraints (character limits, aspect ratios)
* proof slots (where evidence must appear)
* motion allowances (what can animate)

Example modules:

* Hero (headline, subhead, CTA, proof chip, hero media)
* Bento features (cards: icon, benefit, proof, mini demo)
* “How it works” (3-step)
* Use cases (persona-specific)
* Social proof strip
* Pricing
* FAQ (objection handling)
* Final CTA

### 9.2 Selection logic (how the system chooses structure)

Inputs:

* CTA type (trial/demo/waitlist)
* product complexity (low/med/high)
* proof strength (weak/med/strong)
* price sensitivity (low/high)
* category trust requirement (low/high)

Outputs:

* short page vs long narrative
* early pricing vs late pricing vs no pricing
* heavier proof earlier if trust-sensitive
* bento vs storyline vs hybrid

---

# 10) Automated QA: the guardrails that keep automation from harming conversion

### 10.1 Truth QA (the hardest and most important)

* every factual claim must cite evidence ledger
* any metric must have definition + measurement method
* comparisons (“3× faster”) require baseline definition

### 10.2 Accessibility + motion QA

* reduced motion mode (disable parallax, large transforms)
* contrast checks
* keyboard navigation and focus states

### 10.3 Performance QA

Animation and ambience must be budgeted. If a “premium” page stutters, it reads as untrustworthy.

---

# 11) Distribution + personalization: variants are the natural output of this system

Once you can generate variants cheaply, routing becomes the next lever.

Unbounce Smart Traffic is described as using AI optimization to match visitors to the landing page variant they’re most likely to convert on. ([Unbounce][21])
This pairs naturally with your Strategic Source File:

* Variant A: speed angle (analysts)
* Variant B: cost angle (CFO/ops)
* Variant C: compliance angle (enterprise)
* Variant D: simplicity angle (founders)

---

# 12) How this evolves landing pages (theory-driven prediction)

### 12.1 Landing pages become “living product surfaces”

Because the system can:

* explore the product autonomously
* capture new flows automatically
* regenerate assets/videos on each release
* re-route visitors by intent

The page stops being a static marketing artifact and becomes a continuously updated “product story renderer.”

### 12.2 Motion becomes more stateful and product-linked

Instead of generic scroll effects, motion will increasingly:

* mirror the product’s interaction patterns
* use interactive animation systems (state machines) for responsive storytelling

Rive’s state machines are explicitly designed to connect animations and drive transitions with logic for interactive motion graphics. ([Rive][22])

### 12.3 Branding becomes more tokenized (and therefore more generatable)

With design tokens standardized for exchange between tools, brand kits become portable across page builders, codebases, and creative pipelines. ([Design Tokens][9])

### 12.4 Pre-launch validation becomes standard in the loop

Predictive heatmaps will likely be used as a fast hierarchy sanity check (not as a replacement for real user tests). ([Microsoft Clarity][5])

---

# 13) Quick-start implementation plan (minimal viable automation)

### Week 1: Build the truth layer

* generate Product Reality Map from repo + docs + one analytics source
* create evidence ledger structure

### Week 2: Build the capture layer

* Storybook snapshot export for key components/states ([Storybook][2])
* Playwright scripts for 3–5 golden paths + video capture ([Playwright][3])

### Week 3: Build the assembly layer

* define 10–15 landing page modules
* build Page Recipe compiler (inputs → page)

### Week 4: Build the video layer

* Remotion component library
* dataset render variants ([Remotion][16])

### Week 5+: Variants + routing

* persona variants
* optional routing (e.g., Smart Traffic) ([Unbounce][21])

---

## If you want, I can produce the actual “Marketing Source of Truth” template files

I can output:

* a complete JSON schema (Reality Map, Strategic Source File, Brand Kit tokens, Asset Manifest, Page Recipe, Video Recipe)
* a module library spec (what each landing module needs)
* a deterministic ruleset for variant generation (persona × channel × claim-evidence constraints)

To ground it, paste either:

* a single feature (like your export example), **or**
* a link-free summary of your product + pricing + target users + 3–5 core flows you want to showcase.

[1]: https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-3-deep-think/ "Gemini 3 Deep Think: AI model update designed for science"
[2]: https://storybook.js.org/docs/writing-tests/visual-testing "Visual tests | Storybook docs"
[3]: https://playwright.dev/docs/videos "Videos | Playwright"
[4]: https://clarity.microsoft.com/?utm_source=chatgpt.com "Microsoft Clarity - Free Heatmaps & Session Recordings"
[5]: https://clarity.microsoft.com/predictive-heatmaps?utm_source=chatgpt.com "Predictive Heatmaps"
[6]: https://attentioninsight.com/technology/?utm_source=chatgpt.com "Predictive Eye Tracking Technology Explained"
[7]: https://www.tobii.com/blog/ai-actual-intelligence?utm_source=chatgpt.com "AI: Actual Intelligence! Predictive Models vs. Eye Tracking"
[8]: https://www.qualtrics.com/articles/strategy-research/brand-architecture/ "The Complete Guide to Brand Architecture - Qualtrics"
[9]: https://www.designtokens.org/TR/2025.10/format/ "Design Tokens Format Module 2025.10"
[10]: https://m3.material.io/styles/icons/applying-icons?utm_source=chatgpt.com "Icons – Material Design 3"
[11]: https://developer.apple.com/design/human-interface-guidelines/sf-symbols?utm_source=chatgpt.com "SF Symbols | Apple Developer Documentation"
[12]: https://lucide.dev/?utm_source=chatgpt.com "Lucide Icons"
[13]: https://adobe.design/stories/leading-design/how-to-design-effective-icons-part-2?utm_source=chatgpt.com "How to design effective icons, Part 2"
[14]: https://www.remotion.dev/ "Remotion | Make videos programmatically"
[15]: https://www.remotion.dev/docs/parameterized-rendering "Parameterized videos | Remotion | Make videos programmatically"
[16]: https://www.remotion.dev/docs/dataset-render?utm_source=chatgpt.com "Render videos programmatically from a dataset"
[17]: https://www.remotion.dev/docs/renderer/render-media?utm_source=chatgpt.com "renderMedia() | Remotion | Make videos programmatically"
[18]: https://www.remotion.dev/docs/renderer/render-still?utm_source=chatgpt.com "renderStill() | Remotion | Make videos programmatically"
[19]: https://www.remotion.dev/docs/web-renderer/render-media-on-web?utm_source=chatgpt.com "renderMediaOnWeb() | Remotion | Make videos ..."
[20]: https://www.remotion.dev/docs/render?utm_source=chatgpt.com "Render your video"
[21]: https://unbounce.com/product/smart-traffic/?utm_source=chatgpt.com "Unbounce Smart Traffic - AI-based Landing Page ..."
[22]: https://help.rive.app/editor/state-machine?utm_source=chatgpt.com "State Machine Overview"
