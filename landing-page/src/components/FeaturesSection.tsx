import { useRef, useEffect, useState } from "react";
import { useInView } from "motion/react";
import { BlurFade } from "@/components/ui/BlurFade";
import { MagicCard } from "@/components/ui/MagicCard";

/* ─── Routing demo ─── */
function RoutingDemo() {
  const lines = [
    "def authenticate(user):",
    "  validate_token()",
    "  check_session()",
    "  return grant()",
  ];

  return (
    <div className="h-40 flex items-center justify-center px-4">
      <div className="w-full max-w-xs rounded-lg bg-white/[0.03] border border-white/[0.06] p-4">
        {lines.map((line, i) => (
          <div key={i} className="flex items-center gap-2">
            <span className="text-white/20 font-mono text-[10px] select-none">
              {i === 0 ? "▸" : i === 3 ? "◂" : "│"}
            </span>
            <code className="font-mono text-xs text-white/60">{line}</code>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── Self-healing demo ─── */
function SelfHealingDemo() {
  const steps = [
    { icon: "✕", label: "Test fails", color: "border-red-400/40 text-red-400" },
    { icon: "⌕", label: "Root cause", color: "border-yellow-400/40 text-yellow-400" },
    { icon: "⚙", label: "Fix applied", color: "border-white/40 text-white/70" },
    { icon: "✓", label: "Tests pass", color: "border-green-400/40 text-green-400" },
  ];

  return (
    <div className="h-40 flex items-center justify-center px-4">
      <div className="flex items-center gap-2">
        {steps.map((step, i) => (
          <div key={i} className="flex items-center gap-2">
            <div className="flex flex-col items-center gap-1.5">
              <div
                className={`w-9 h-9 rounded-full border-2 flex items-center justify-center text-sm ${step.color}`}
              >
                {step.icon}
              </div>
              <span className="font-mono text-[9px] text-white/35 whitespace-nowrap">
                {step.label}
              </span>
            </div>
            {i < steps.length - 1 && (
              <svg width="20" height="8" className="text-white/15 mb-5">
                <path d="M0 4 L16 4 M12 1 L16 4 L12 7" stroke="currentColor" strokeWidth="1" fill="none" />
              </svg>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── Coverage demo ─── */
function CoverageDemo() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, margin: "-60px" });
  const [filledCount, setFilledCount] = useState(0);
  const total = 12;

  useEffect(() => {
    if (!inView) return;
    let current = 0;
    const interval = setInterval(() => {
      current++;
      setFilledCount(current);
      if (current >= total) clearInterval(interval);
    }, 150);
    return () => clearInterval(interval);
  }, [inView]);

  return (
    <div ref={ref} className="h-40 flex flex-col items-center justify-center gap-3 px-4">
      <div className="grid grid-cols-4 gap-1.5">
        {Array.from({ length: total }).map((_, i) => (
          <div
            key={i}
            className={`w-6 h-6 rounded border border-white/[0.06] transition-colors duration-300 ${
              i < filledCount ? "bg-white/15" : "bg-transparent"
            }`}
          />
        ))}
      </div>
      <span className="font-mono text-xs text-white/40">
        {filledCount}/{total}
      </span>
    </div>
  );
}

/* ─── Clarity demo ─── */
function ClarityDemo() {
  const options = ["Stateless JWT", "Session tokens", "OAuth delegation"];

  return (
    <div className="h-40 flex items-center justify-center px-4">
      <div className="flex items-center gap-3">
        {/* Underspec indicator */}
        <div className="flex flex-col items-center gap-1">
          <div className="w-8 h-8 rounded-full border-2 border-yellow-400/40 flex items-center justify-center text-yellow-400 text-sm">
            ?
          </div>
          <span className="font-mono text-[9px] text-white/30">unclear</span>
        </div>

        <svg width="16" height="8" className="text-white/15">
          <path d="M0 4 L12 4 M8 1 L12 4 L8 7" stroke="currentColor" strokeWidth="1" fill="none" />
        </svg>

        {/* Options */}
        <div className="flex flex-col gap-1.5">
          {options.map((opt, i) => (
            <label key={i} className="flex items-center gap-2 cursor-default">
              <div
                className={`w-3 h-3 rounded-full border ${
                  i === 0
                    ? "border-white/40 bg-white/20"
                    : "border-white/15 bg-transparent"
                }`}
              />
              <span className="font-mono text-[10px] text-white/50">{opt}</span>
            </label>
          ))}
        </div>

        <svg width="16" height="8" className="text-white/15">
          <path d="M0 4 L12 4 M8 1 L12 4 L8 7" stroke="currentColor" strokeWidth="1" fill="none" />
        </svg>

        {/* Constraint set */}
        <div className="flex flex-col items-center gap-1">
          <div className="w-8 h-8 rounded-full border-2 border-green-400/40 flex items-center justify-center text-green-400 text-sm">
            ✓
          </div>
          <span className="font-mono text-[9px] text-white/30">set</span>
        </div>
      </div>
    </div>
  );
}

/* ─── Workspaces demo ─── */
function WorkspacesDemo() {
  return (
    <div className="h-40 flex items-center justify-center px-4">
      <svg width="220" height="90" viewBox="0 0 220 90" fill="none">
        {/* Child workspaces → dirty */}
        <line x1="10" y1="15" x2="60" y2="15" stroke="rgba(255,255,255,0.15)" strokeWidth="1" />
        <line x1="10" y1="35" x2="60" y2="35" stroke="rgba(255,255,255,0.15)" strokeWidth="1" />
        <line x1="10" y1="55" x2="60" y2="55" stroke="rgba(255,255,255,0.15)" strokeWidth="1" />

        {/* Converge to dirty */}
        <line x1="60" y1="15" x2="85" y2="35" stroke="rgba(255,255,255,0.15)" strokeWidth="1" />
        <line x1="60" y1="35" x2="85" y2="35" stroke="rgba(255,255,255,0.15)" strokeWidth="1" />
        <line x1="60" y1="55" x2="85" y2="35" stroke="rgba(255,255,255,0.15)" strokeWidth="1" />

        {/* Dirty workspace zone */}
        <rect x="85" y="22" width="40" height="26" rx="4" fill="rgba(255,255,255,0.04)" stroke="rgba(255,255,255,0.12)" strokeWidth="1" />
        <text x="93" y="39" fill="rgba(255,255,255,0.35)" fontSize="8" fontFamily="monospace">dirty</text>

        {/* Gate arrow dirty → clean */}
        <line x1="125" y1="35" x2="150" y2="35" stroke="rgba(255,255,255,0.2)" strokeWidth="1" strokeDasharray="3 2" />
        {/* Gate icon */}
        <text x="133" y="30" fill="rgba(255,255,255,0.25)" fontSize="8" fontFamily="monospace">CI</text>

        {/* Clean workspace zone */}
        <rect x="150" y="22" width="40" height="26" rx="4" fill="rgba(255,255,255,0.06)" stroke="rgba(255,255,255,0.2)" strokeWidth="1" />
        <text x="155" y="39" fill="rgba(255,255,255,0.45)" fontSize="8" fontFamily="monospace">clean</text>

        {/* Arrow to main */}
        <line x1="190" y1="35" x2="210" y2="35" stroke="rgba(255,255,255,0.3)" strokeWidth="1.5" />
        <circle cx="210" cy="35" r="3" fill="rgba(255,255,255,0.2)" stroke="rgba(255,255,255,0.35)" strokeWidth="1" />

        {/* Labels */}
        <text x="3" y="11" fill="rgba(255,255,255,0.2)" fontSize="7" fontFamily="monospace">agent-1</text>
        <text x="3" y="31" fill="rgba(255,255,255,0.2)" fontSize="7" fontFamily="monospace">agent-2</text>
        <text x="3" y="51" fill="rgba(255,255,255,0.2)" fontSize="7" fontFamily="monospace">agent-3</text>

        {/* Dirty workspace feeds child context (dashed line back) */}
        <path d="M 95 48 L 95 70 L 35 70 L 35 58" stroke="rgba(255,255,255,0.08)" strokeWidth="1" strokeDasharray="2 2" fill="none" />
        <text x="45" y="78" fill="rgba(255,255,255,0.15)" fontSize="7" fontFamily="monospace">shared context</text>
      </svg>
    </div>
  );
}

/* ─── Transparency demo ─── */
function TransparencyDemo() {
  const entries = [
    { hash: "a3f8c2", msg: "route auth_lib to L1" },
    { hash: "7b21e0", msg: "promote slice to L2" },
    { hash: "e9d4f1", msg: "gate passed: merge to main" },
  ];

  return (
    <div className="h-40 flex items-center justify-center px-4">
      <div className="flex items-center gap-3">
        {entries.map((entry, i) => (
          <div key={i} className="flex items-center gap-3">
            <div className="rounded-lg border border-white/[0.06] bg-white/[0.03] px-3 py-2">
              <span className="font-mono text-[10px] text-white/30 block">
                {entry.hash}
              </span>
              <span className="font-mono text-xs text-white/55 block mt-0.5">
                {entry.msg}
              </span>
            </div>
            {i < entries.length - 1 && (
              <svg width="24" height="16" viewBox="0 0 24 16" fill="none" className="shrink-0">
                {/* Lock icon */}
                <rect x="7" y="7" width="10" height="8" rx="1.5" stroke="rgba(255,255,255,0.2)" strokeWidth="1" fill="none" />
                <path d="M10 7V5a2 2 0 0 1 4 0v2" stroke="rgba(255,255,255,0.2)" strokeWidth="1" fill="none" />
              </svg>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── Card data ─── */
const features = [
  {
    span: "md:col-span-3",
    eyebrow: "Routing",
    title: "Edits in place, never rewrites",
    text: "The system routes code to where it belongs and edits it in place. No extraction, no rephrasing. Your requirements travel through the pipeline without losing information.",
    Demo: RoutingDemo,
  },
  {
    span: "md:col-span-3",
    eyebrow: "Self-healing",
    title: "Failures trace back to the source",
    text: "When tests fail, an investigator works in a CI sandbox to root cause the failure. It applies a fix, confirms tests pass, then submits a report to the planner.",
    Demo: SelfHealingDemo,
  },
  {
    span: "md:col-span-2",
    eyebrow: "Coverage",
    title: "Every requirement tracked",
    text: "A coverage ledger maps every spec requirement to the code that implements it. Nothing gets marked complete until the ledger confirms full coverage.",
    Demo: CoverageDemo,
  },
  {
    span: "md:col-span-2",
    eyebrow: "Clarity",
    title: "Ambiguity stops the line",
    text: "When the system hits something underspecified, it researches the space, generates diverse constraint options, and asks you to choose. Your answer becomes a permanent rule.",
    Demo: ClarityDemo,
  },
  {
    span: "md:col-span-2",
    eyebrow: "Workspaces",
    title: "Dirty work, clean output",
    text: "Agents work in isolated child workspaces branched from a shared dirty workspace. A separate clean workspace holds only code that has passed every gate. Nothing crosses from dirty to clean without passing CI.",
    Demo: WorkspacesDemo,
  },
  {
    span: "md:col-span-6",
    eyebrow: "Transparency",
    title: "Trust through transparency",
    text: "Every decision the system makes gets written to append-only logs with integrity chaining. The chain is tamper-evident. If a log entry gets altered after the fact, the hash chain breaks.",
    Demo: TransparencyDemo,
  },
] as const;

export function FeaturesSection() {
  return (
    <section id="features" className="relative z-10 py-28 px-6">
      <div className="mx-auto max-w-5xl">
        <BlurFade>
          <p className="font-mono text-xs uppercase tracking-widest text-white/35 mb-4">
            Features
          </p>
          <h2 className="text-3xl sm:text-4xl font-semibold tracking-tight mb-12">
            What you get
          </h2>
        </BlurFade>

        <div className="grid grid-cols-1 md:grid-cols-6 gap-5">
          {features.map((feature, i) => (
            <BlurFade
              key={feature.eyebrow}
              delay={i * 0.08}
              className={feature.span}
            >
              <MagicCard className="h-full rounded-2xl p-0">
                <feature.Demo />
                <div className="px-6 pb-6">
                  <p className="font-mono text-[10px] uppercase tracking-widest text-white/30 mb-2">
                    {feature.eyebrow}
                  </p>
                  <h3 className="text-lg font-semibold tracking-tight text-white/90 mb-2">
                    {feature.title}
                  </h3>
                  <p className="text-sm text-white/45 leading-relaxed">
                    {feature.text}
                  </p>
                </div>
              </MagicCard>
            </BlurFade>
          ))}
        </div>
      </div>
    </section>
  );
}
