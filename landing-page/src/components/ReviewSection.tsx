import { BlurFade } from "@/components/ui/BlurFade";
import { MagicCard } from "@/components/ui/MagicCard";

/* ─── Demo: Question ─── */
function QuestionDemo() {
  return (
    <div className="h-32 flex items-center justify-center gap-4 font-mono text-[11px]">
      {/* signal dots */}
      <div className="flex flex-col gap-1.5">
        {[0.6, 0.45, 0.3].map((op) => (
          <div
            key={op}
            className="w-2 h-2 rounded-full"
            style={{ background: `rgba(255,255,255,${op})` }}
          />
        ))}
      </div>

      {/* arrow */}
      <svg width="24" height="12" className="text-white/20">
        <path
          d="M0 6h20m0 0l-4-4m4 4l-4 4"
          stroke="currentColor"
          strokeWidth="1"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>

      {/* queue */}
      <div className="flex flex-col gap-1">
        {["sig.0x3f", "sig.0xa2", "sig.0x17"].map((s) => (
          <div
            key={s}
            className="px-2 py-0.5 rounded border border-white/10 bg-white/[0.03] text-white/30"
          >
            {s}
          </div>
        ))}
      </div>

      {/* arrow */}
      <svg width="24" height="12" className="text-white/20">
        <path
          d="M0 6h20m0 0l-4-4m4 4l-4 4"
          stroke="currentColor"
          strokeWidth="1"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>

      {/* output */}
      <div className="w-8 h-8 rounded-lg border border-white/15 bg-white/[0.04] flex items-center justify-center text-lg text-white/50">
        ?
      </div>
    </div>
  );
}

/* ─── Demo: Constraint ─── */
function ConstraintDemo() {
  return (
    <div className="h-32 flex items-center justify-center gap-3 font-mono text-[10px]">
      {/* input text */}
      <div className="flex flex-col gap-0.5 text-white/40 leading-tight max-w-[90px]">
        <span>Tokens must verify</span>
        <span>without server calls</span>
      </div>

      {/* arrow */}
      <svg width="24" height="12" className="text-white/20 shrink-0">
        <path
          d="M0 6h20m0 0l-4-4m4 4l-4 4"
          stroke="currentColor"
          strokeWidth="1"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>

      {/* YAML block */}
      <div className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-white/35 leading-relaxed">
        <div>
          <span className="text-white/50">scope:</span> token_lib
        </div>
        <div>
          <span className="text-white/50">requires:</span> stateless
        </div>
        <div>
          <span className="text-white/50">rationale:</span> no_trips
        </div>
      </div>
    </div>
  );
}

/* ─── Demo: Audit ─── */
function AuditDemo() {
  const entries = [
    { hash: "a3f8", action: "signal.emit" },
    { hash: "7b21", action: "constraint.apply" },
    { hash: "e9d4", action: "promote.pass" },
  ];

  return (
    <div className="h-32 flex items-center justify-center">
      <div className="flex flex-col gap-1.5 font-mono text-[10px]">
        {entries.map((entry, i) => (
          <div key={entry.hash} className="flex items-center gap-2">
            {/* chain link icon */}
            <svg width="12" height="12" className="text-white/25 shrink-0">
              <path
                d="M4 6a2 2 0 0 1 2-2h0a2 2 0 0 1 2 2h0a2 2 0 0 1-2 2h0a2 2 0 0 1-2-2z"
                stroke="currentColor"
                strokeWidth="1"
                fill="none"
              />
            </svg>

            <span className="text-white/50">{entry.hash}</span>
            <span className="text-white/20">&rarr;</span>
            <span
              className="text-white/35"
              style={{ animationDelay: `${i * 200}ms` }}
            >
              {entry.action}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── Card data ─── */
const cards = [
  {
    step: "01",
    title: "The Intent Agent asks when something is unclear",
    text: "Internal agents never contact you directly. They emit signals when blocked. The Intent Agent collects these into a priority queue with full context about what is unclear and which part of the build is waiting. You see one focused question at a time.",
    Demo: QuestionDemo,
  },
  {
    step: "02",
    title: "Your answer becomes a permanent rule",
    text: "You provide a constraint, not a solution. The system decides how to implement it. Your constraint gets stored as YAML and applied to every future decision on that slice. The blocked work resumes. Everything else kept building the whole time.",
    Demo: ConstraintDemo,
  },
  {
    step: "03",
    title: "Every decision lives on disk",
    text: "Append-only logs record every signal and constraint the system processes. Pick any function in the output and trace the chain back to the spec line that produced it. The coverage ledger shows what is still missing.",
    Demo: AuditDemo,
  },
] as const;

/* ─── Component ─── */
export function ReviewSection() {
  return (
    <section id="review" className="relative z-10 py-28">
      <div className="mx-auto max-w-5xl px-6">
        <BlurFade>
          <p className="font-mono text-xs uppercase tracking-widest text-white/35 mb-3">
            How you interact
          </p>
        </BlurFade>

        <BlurFade delay={0.05}>
          <h2 className="text-3xl font-semibold mb-12">
            You answer questions. The system builds.
          </h2>
        </BlurFade>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
          {cards.map((card, i) => (
            <BlurFade key={card.step} delay={i * 0.12}>
              <MagicCard className="p-5 h-full">
                <div className="flex flex-col gap-4">
                  <card.Demo />

                  <p className="font-mono text-xs text-white/35">
                    Step {card.step}
                  </p>
                  <h3 className="text-base font-medium text-white/90 leading-snug">
                    {card.title}
                  </h3>
                  <p className="text-sm text-white/50 leading-relaxed">
                    {card.text}
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
