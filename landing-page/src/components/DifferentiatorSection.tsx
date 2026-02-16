import { useRef, useState, useEffect } from "react";
import { motion } from "motion/react";
import { BlurFade } from "@/components/ui/BlurFade";

const bars = [
  { label: "Oulipoly Automaton", value: 100, fill: "bg-white/25" },
  { label: "Opus 4.6", value: 73, fill: "bg-white/12" },
] as const;

function useNativeInView(ref: React.RefObject<HTMLElement | null>) {
  const [inView, setInView] = useState(false);
  useEffect(() => {
    if (!ref.current) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setInView(true);
          observer.disconnect();
        }
      },
      { threshold: 0.1 },
    );
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, [ref]);
  return inView;
}

function AnimatedNumber({
  value,
  inView,
  delay,
}: {
  value: number;
  inView: boolean;
  delay: number;
}) {
  const [display, setDisplay] = useState(0);

  useEffect(() => {
    if (!inView) return;
    const timeout = setTimeout(() => {
      const start = performance.now();
      const duration = 1400;
      function tick(now: number) {
        const elapsed = now - start;
        const progress = Math.min(1, elapsed / duration);
        // ease-out cubic
        const eased = 1 - Math.pow(1 - progress, 3);
        setDisplay(Math.round(eased * value));
        if (progress < 1) requestAnimationFrame(tick);
      }
      requestAnimationFrame(tick);
    }, delay * 1000);
    return () => clearTimeout(timeout);
  }, [inView, value, delay]);

  return <>{display}%</>;
}

function AccuracyBar({
  label,
  value,
  fill,
  delay,
}: {
  label: string;
  value: number;
  fill: string;
  delay: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useNativeInView(ref);

  return (
    <div ref={ref} className="flex items-center gap-3">
      <span className="w-[140px] shrink-0 text-right font-mono text-xs text-white/50">
        {label}
      </span>
      <div className="flex-1 h-5 rounded bg-white/[0.03] border border-white/[0.06] overflow-hidden">
        <motion.div
          className={`h-full rounded ${fill}`}
          initial={{ width: "0%" }}
          animate={inView ? { width: `${value}%` } : { width: "0%" }}
          transition={{ duration: 1.4, delay, ease: [0.22, 1, 0.36, 1] }}
        />
      </div>
      <span className="w-12 text-right font-mono text-xs text-white/70">
        <AnimatedNumber value={value} inView={inView} delay={delay} />
      </span>
    </div>
  );
}

export function DifferentiatorSection() {
  return (
    <section id="differentiator" className="relative z-10 py-28 px-6">
      <BlurFade>
        <div className="mx-auto max-w-4xl">
          {/* Eyebrow */}
          <p className="font-mono text-xs uppercase tracking-widest text-white/35 mb-4">
            What makes us different
          </p>

          {/* Headline */}
          <h2 className="text-3xl sm:text-4xl font-semibold tracking-tight mb-12">
            A pipeline stands between AI and your branch
          </h2>

          {/* Side-by-side layout */}
          <div className="flex flex-col lg:flex-row gap-12 lg:gap-16">
            {/* LEFT column — text */}
            <div className="lg:w-[55%]">
              <p className="text-lg text-white/55 leading-relaxed">
                Other tools give you raw AI output and leave quality control to
                you. Oulipoly Automaton runs code through layered gates before it
                reaches your branch. Every function that lands in your project
                has passed compliance checks at every layer. A coverage ledger
                maps each requirement to the code that implements it.
              </p>
            </div>

            {/* RIGHT column — accuracy bars */}
            <div className="lg:w-[45%] flex flex-col gap-4 justify-center">
              {bars.map((bar, i) => (
                <AccuracyBar
                  key={bar.label}
                  label={bar.label}
                  value={bar.value}
                  fill={bar.fill}
                  delay={i * 0.2}
                />
              ))}
              <p className="text-xs text-white/25 mt-2">
                Internal benchmark: spec coverage across accuracy, architecture,
                and code quality
              </p>
            </div>
          </div>
        </div>
      </BlurFade>
    </section>
  );
}
