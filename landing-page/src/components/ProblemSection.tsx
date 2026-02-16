import { BlurFade } from "@/components/ui/BlurFade";
import { MagicCard } from "@/components/ui/MagicCard";

/* ─── Icon components ─── */
function XCircleIcon({ className }: { className?: string }) {
  return (
    <svg
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      className={className}
    >
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="1.5" />
      <path
        d="M15 9l-6 6M9 9l6 6"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

function TriangleWarningIcon({ className }: { className?: string }) {
  return (
    <svg
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      className={className}
    >
      <path
        d="M12 3L2 21h20L12 3z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <path
        d="M12 10v4"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
      <circle cx="12" cy="17" r="0.5" fill="currentColor" />
    </svg>
  );
}

function RefreshIcon({ className }: { className?: string }) {
  return (
    <svg
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      className={className}
    >
      <path
        d="M21 3v6h-6"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M3 12a9 9 0 0 1 15.36-6.36L21 9"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M3 21v-6h6"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M21 12a9 9 0 0 1-15.36 6.36L3 15"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function EyeIcon({ className }: { className?: string }) {
  return (
    <svg
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      className={className}
    >
      <path
        d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8S1 12 1 12z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <circle
        cx="12"
        cy="12"
        r="3"
        stroke="currentColor"
        strokeWidth="1.5"
      />
    </svg>
  );
}

/* ─── Card data ─── */
const problems = [
  {
    icon: XCircleIcon,
    iconColor: "text-red-400",
    title: "AI forgets things",
    text: "Your AI handles small tasks fine. As your project grows, it drops details. 45 out of 52 requirements? You won't notice the 7 missing until production breaks.",
  },
  {
    icon: TriangleWarningIcon,
    iconColor: "text-yellow-400",
    title: "AI guesses instead of asking",
    text: "When requirements are unclear, AI fills in the blanks with assumptions. You get code that looks right but does the wrong thing. The bug hides behind confident syntax.",
  },
  {
    icon: RefreshIcon,
    iconColor: "text-red-400",
    title: "Fixes land at the wrong layer",
    text: "A logic bug gets patched in the architecture layer. The patch works today but creates coupling that breaks tomorrow. No system ensures fixes go to the right level.",
  },
  {
    icon: EyeIcon,
    iconColor: "text-yellow-400",
    title: "Nobody checks the AI's work",
    text: "You are the only quality gatekeeper. One person, reviewing AI-generated code you may not fully understand.",
  },
] as const;

/* ─── Component ─── */
export function ProblemSection() {
  return (
    <section
      id="problems"
      className="relative z-10 py-28"
      style={{
        background:
          "linear-gradient(180deg, rgba(255,255,255,0.015) 0%, transparent 100%)",
      }}
    >
      <div className="mx-auto max-w-3xl px-6">
        <BlurFade>
          <h2 className="text-3xl font-semibold mb-12 text-center">
            The gaps AI tools leave open
          </h2>
        </BlurFade>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          {problems.map((problem, i) => {
            const Icon = problem.icon;
            return (
              <BlurFade key={problem.title} delay={i * 0.1} direction="left">
                <MagicCard className="p-5 h-full">
                  <div className="flex flex-col gap-3">
                    <Icon className={problem.iconColor} />
                    <h3 className="text-base font-medium text-white/90">
                      {problem.title}
                    </h3>
                    <p className="text-sm text-white/50 leading-relaxed">
                      {problem.text}
                    </p>
                  </div>
                </MagicCard>
              </BlurFade>
            );
          })}
        </div>
      </div>
    </section>
  );
}
