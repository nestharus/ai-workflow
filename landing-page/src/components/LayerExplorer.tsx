import { useState, useEffect, useRef, useCallback } from "react";
import { motion, useInView, AnimatePresence } from "motion/react";
import { BlurFade } from "@/components/ui/BlurFade";

/* ─── Tab definitions ─── */
type TabId = "p0" | "l1" | "l2" | "l3" | "main";

interface TabDef {
  id: TabId;
  label: string;
  description: string;
}

const tabs: TabDef[] = [
  {
    id: "p0",
    label: "P0",
    description:
      "The spec gets classified and routed into library buckets. Each bucket implements in parallel. When a slice hits a gap, planning researches and integrates a solution.",
  },
  {
    id: "l1",
    label: "L1",
    description:
      "Libraries implement in parallel. Each slice builds independently. When ambiguity is detected, the slice halts and planning researches a solution before resuming.",
  },
  {
    id: "l2",
    label: "L2",
    description:
      "Five architecture reviewers analyze the promoted code. Each reviewer evaluates a different dimension. The gate passes only when all reviewers approve.",
  },
  {
    id: "l3",
    label: "L3",
    description:
      "Quality review examines code complexity, diff impact, and test coverage. Lines that need refactoring are highlighted and improved.",
  },
  {
    id: "main",
    label: "Main",
    description:
      "All branches converge into the main branch. Every gate has passed. Coverage is complete. The code is production-ready.",
  },
];

const AUTO_CYCLE_MS = 7000;
const PAUSE_AFTER_CLICK_MS = 12000;

/* ─── Shared animation ease ─── */
const ease = [0.22, 1, 0.36, 1] as const;

/* ─── P0 Discovery view ─── */
const specBlocks = [
  "Authentication flow",
  "Session management",
  "Token validation",
  "User profiles",
  "Rate limiting",
];
const libraryTargets = [
  "auth_lib",
  "session_lib",
  "token_lib",
  "user_lib",
  "rate_lib",
];

function P0View({ animationKey }: { animationKey: number }) {
  return (
    <div className="relative w-full flex items-center justify-between px-6 sm:px-10 py-6">
      {/* Left: spec blocks */}
      <div className="flex flex-col gap-2">
        {specBlocks.map((block, i) => (
          <motion.div
            key={`${animationKey}-src-${i}`}
            className="px-3 py-1.5 rounded-md bg-white/[0.05] border border-white/[0.08] font-mono text-[11px] text-white/60 whitespace-nowrap"
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.5, delay: i * 0.1, ease }}
          >
            {block}
          </motion.div>
        ))}
      </div>

      {/* Center: route arrows */}
      <div className="flex flex-col gap-2 mx-2 sm:mx-4">
        {specBlocks.map((_, i) => (
          <motion.div
            key={`${animationKey}-arrow-${i}`}
            className="flex items-center h-[30px]"
            initial={{ opacity: 0, scaleX: 0 }}
            animate={{ opacity: 1, scaleX: 1 }}
            transition={{ duration: 0.4, delay: 0.6 + i * 0.08, ease }}
            style={{ transformOrigin: "left" }}
          >
            <div className="w-12 sm:w-20 h-px bg-gradient-to-r from-white/20 to-white/5" />
            <div className="w-0 h-0 border-t-[3px] border-t-transparent border-b-[3px] border-b-transparent border-l-[5px] border-l-white/20" />
          </motion.div>
        ))}
      </div>

      {/* Right: library targets */}
      <div className="flex flex-col gap-2">
        {libraryTargets.map((target, i) => (
          <motion.div
            key={`${animationKey}-tgt-${i}`}
            className="px-3 py-1.5 rounded-md bg-white/[0.07] border border-white/[0.1] font-mono text-[11px] text-emerald-400/70 whitespace-nowrap"
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.5, delay: 1.0 + i * 0.1, ease }}
          >
            {target}
          </motion.div>
        ))}
      </div>
    </div>
  );
}

/* ─── L1 Build view ─── */
const libNodes = [
  { name: "auth_lib", blocked: false },
  { name: "session_lib", blocked: false },
  { name: "token_lib", blocked: true },
  { name: "user_lib", blocked: false },
  { name: "rate_lib", blocked: false },
  { name: "config_lib", blocked: false },
];

function L1View({ animationKey }: { animationKey: number }) {
  const [phase, setPhase] = useState(0);
  const timerRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    timerRef.current.forEach(clearTimeout);
    timerRef.current = [];

    const t0 = setTimeout(() => setPhase(0), 0);
    const t1 = setTimeout(() => setPhase(1), 600);
    const t2 = setTimeout(() => setPhase(2), 1400);
    const t3 = setTimeout(() => setPhase(3), 3200);
    const t4 = setTimeout(() => setPhase(4), 4400);
    timerRef.current = [t0, t1, t2, t3, t4];

    return () => timerRef.current.forEach(clearTimeout);
  }, [animationKey]);

  return (
    <div className="w-full flex items-center justify-center gap-8 px-6 sm:px-10 py-6">
      {/* Spec blob */}
      <motion.div
        className="shrink-0"
        initial={{ opacity: 0, scale: 0.8 }}
        animate={{
          opacity: 1,
          scale: phase >= 1 ? [1, 1.06, 1] : 1,
        }}
        transition={{ duration: 0.8, ease }}
      >
        <div className="w-20 h-20 rounded-xl bg-white/[0.05] border border-white/[0.1] flex items-center justify-center">
          <span className="font-mono text-[10px] text-white/50">spec.md</span>
        </div>
      </motion.div>

      {/* Node grid */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-2.5">
        {libNodes.map((node, i) => {
          const isBlocked = node.blocked && phase >= 2 && phase < 4;
          const isDone = node.blocked ? phase >= 4 : phase >= 3;
          const progressDelay = node.blocked && phase < 4 ? 0.55 : 0;

          return (
            <motion.div
              key={`${animationKey}-node-${i}`}
              className="w-28 px-2 py-1.5 rounded-md bg-white/[0.04] border border-white/[0.08]"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: phase >= 2 ? 1 : 0, y: phase >= 2 ? 0 : 10 }}
              transition={{ duration: 0.4, delay: i * 0.08, ease }}
            >
              <div className="flex items-center justify-between mb-1">
                <span className="font-mono text-[10px] text-white/55 truncate">
                  {node.name}
                </span>
                {isBlocked && (
                  <span className="text-[10px] text-yellow-400">?</span>
                )}
                {isDone && (
                  <motion.span
                    className="text-[10px] text-emerald-400"
                    initial={{ opacity: 0, scale: 0 }}
                    animate={{ opacity: 1, scale: 1 }}
                    transition={{ duration: 0.3, delay: progressDelay }}
                  >
                    &#10003;
                  </motion.span>
                )}
              </div>
              <div className="h-1 rounded-full bg-white/[0.06] overflow-hidden">
                <motion.div
                  className={`h-full rounded-full ${
                    isBlocked ? "bg-yellow-400/50" : "bg-emerald-400/40"
                  }`}
                  initial={{ width: "0%" }}
                  animate={{
                    width: isBlocked
                      ? "45%"
                      : phase >= 3
                        ? "100%"
                        : "0%",
                  }}
                  transition={{
                    duration: isBlocked ? 0.8 : 1.2,
                    delay: i * 0.06,
                    ease,
                  }}
                />
              </div>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}

/* ─── L2 Architecture view ─── */
const reviewers = [
  "Topology",
  "Coupling",
  "Interface",
  "Cohesion",
  "Contracts",
];

function L2View({ animationKey }: { animationKey: number }) {
  const [litCount, setLitCount] = useState(0);
  const [gatePassed, setGatePassed] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    timerRef.current.forEach(clearTimeout);
    timerRef.current = [];

    const t0 = setTimeout(() => {
      setLitCount(0);
      setGatePassed(false);
    }, 0);
    timerRef.current.push(t0);

    for (let i = 0; i < reviewers.length; i++) {
      const t = setTimeout(() => setLitCount(i + 1), 600 + i * 700);
      timerRef.current.push(t);
    }
    const tGate = setTimeout(
      () => setGatePassed(true),
      600 + reviewers.length * 700 + 500
    );
    timerRef.current.push(tGate);

    return () => timerRef.current.forEach(clearTimeout);
  }, [animationKey]);

  return (
    <div className="relative w-full flex flex-col items-center justify-center gap-6 px-6 py-6">
      {/* Reviewer badges */}
      <div className="flex gap-3 sm:gap-4 flex-wrap justify-center">
        {reviewers.map((name, i) => {
          const lit = i < litCount;
          return (
            <motion.div
              key={`${animationKey}-rev-${i}`}
              className="flex flex-col items-center gap-1.5"
              initial={{ opacity: 0, scale: 0.7 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.4, delay: i * 0.1, ease }}
            >
              <motion.div
                className={`w-9 h-9 rounded-full border flex items-center justify-center font-mono text-[10px] transition-colors duration-500 ${
                  lit
                    ? "bg-emerald-400/15 border-emerald-400/40 text-emerald-400"
                    : "bg-white/[0.03] border-white/[0.08] text-white/30"
                }`}
                animate={
                  lit
                    ? { boxShadow: "0 0 12px rgba(52,211,153,0.2)" }
                    : { boxShadow: "0 0 0px rgba(0,0,0,0)" }
                }
              >
                R{i + 1}
              </motion.div>
              <span className="text-[9px] text-white/40 font-mono">
                {name}
              </span>
            </motion.div>
          );
        })}
      </div>

      {/* Gate bar */}
      <div className="w-full max-w-xs">
        <div className="flex items-center gap-2 mb-1.5">
          <span className="font-mono text-[10px] text-white/40 uppercase tracking-wider">
            Gate
          </span>
          {gatePassed && (
            <motion.span
              className="text-emerald-400 text-xs"
              initial={{ opacity: 0, scale: 0 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.4, ease }}
            >
              &#10003; Passed
            </motion.span>
          )}
        </div>
        <div className="h-2 rounded-full bg-white/[0.05] border border-white/[0.08] overflow-hidden">
          <motion.div
            className="h-full rounded-full"
            initial={{ width: "0%" }}
            animate={{
              width: gatePassed
                ? "100%"
                : `${(litCount / reviewers.length) * 100}%`,
              backgroundColor: gatePassed
                ? "rgba(52, 211, 153, 0.4)"
                : litCount <= 1
                  ? "rgba(248, 113, 113, 0.4)"
                  : litCount <= 3
                    ? "rgba(251, 191, 36, 0.4)"
                    : "rgba(52, 211, 153, 0.4)",
            }}
            transition={{ duration: 0.6, ease }}
          />
        </div>
      </div>
    </div>
  );
}

/* ─── L3 Quality view ─── */
const codeLines = [
  { num: 11, text: "def validate_token(token: str):" },
  { num: 12, text: '    """Validate JWT and return claims."""' },
  { num: 13, text: "    header = decode_header(token)" },
  { num: 14, text: "    if not header.get('alg'):", highlight: "yellow" as const },
  { num: 15, text: "        return None" },
  { num: 16, text: "    payload = decode(token, key, algorithms)", highlight: "blue" as const },
];

const metrics = [
  { label: "Complexity", value: 35, color: "bg-yellow-400/40" },
  { label: "Diff impact", value: 60, color: "bg-white/20" },
  { label: "Coverage", value: 90, color: "bg-emerald-400/40" },
];

function L3View({ animationKey }: { animationKey: number }) {
  const [showMetrics, setShowMetrics] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    const t0 = setTimeout(() => setShowMetrics(false), 0);
    timerRef.current = setTimeout(() => setShowMetrics(true), 1800);
    return () => {
      clearTimeout(t0);
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [animationKey]);

  return (
    <div className="relative w-full flex flex-col sm:flex-row items-center justify-center gap-6 px-4 sm:px-8 py-6">
      {/* Code listing */}
      <div className="rounded-lg bg-black/30 border border-white/[0.08] p-3 font-mono text-[11px] leading-[1.7] overflow-hidden">
        {codeLines.map((line, i) => {
          const bgClass =
            line.highlight === "yellow"
              ? "bg-yellow-400/10"
              : line.highlight === "blue"
                ? "bg-sky-400/10"
                : "";
          return (
            <motion.div
              key={`${animationKey}-line-${i}`}
              className={`flex whitespace-nowrap px-2 rounded-sm ${bgClass}`}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.3, delay: i * 0.12, ease }}
            >
              <span className="w-7 text-right mr-3 text-white/20 select-none shrink-0">
                {line.num}
              </span>
              <span
                className={
                  line.highlight === "yellow"
                    ? "text-yellow-300/70"
                    : line.highlight === "blue"
                      ? "text-sky-300/70"
                      : "text-white/50"
                }
              >
                {line.text}
              </span>
            </motion.div>
          );
        })}
      </div>

      {/* Metrics */}
      <div className="flex flex-col gap-3 min-w-[140px]">
        {metrics.map((m, i) => (
          <motion.div
            key={`${animationKey}-metric-${i}`}
            initial={{ opacity: 0, x: 10 }}
            animate={{
              opacity: showMetrics ? 1 : 0,
              x: showMetrics ? 0 : 10,
            }}
            transition={{ duration: 0.5, delay: i * 0.15, ease }}
          >
            <div className="flex justify-between mb-1">
              <span className="font-mono text-[10px] text-white/40">
                {m.label}
              </span>
              <span className="font-mono text-[10px] text-white/55">
                {m.value}%
              </span>
            </div>
            <div className="h-1.5 rounded-full bg-white/[0.05] overflow-hidden">
              <motion.div
                className={`h-full rounded-full ${m.color}`}
                initial={{ width: "0%" }}
                animate={{ width: showMetrics ? `${m.value}%` : "0%" }}
                transition={{ duration: 1, delay: i * 0.15, ease }}
              />
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}

/* ─── Main Merge view ─── */
function MainView({ animationKey }: { animationKey: number }) {
  const [phase, setPhase] = useState(0);
  const timerRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    timerRef.current.forEach(clearTimeout);
    timerRef.current = [];

    const t0 = setTimeout(() => setPhase(0), 0);
    const t1 = setTimeout(() => setPhase(1), 400);
    const t2 = setTimeout(() => setPhase(2), 1800);
    const t3 = setTimeout(() => setPhase(3), 2800);
    const t4 = setTimeout(() => setPhase(4), 3600);
    timerRef.current = [t0, t1, t2, t3, t4];

    return () => timerRef.current.forEach(clearTimeout);
  }, [animationKey]);

  const branchNames = ["feature/auth", "feature/session", "feature/tokens"];

  return (
    <div className="relative w-full flex items-center justify-center px-6 py-6">
      <svg
        viewBox="0 0 400 200"
        className="w-full max-w-md h-auto"
        fill="none"
      >
        {/* Branch lines */}
        {branchNames.map((_, i) => {
          const y = 40 + i * 55;
          return (
            <g key={`${animationKey}-branch-${i}`}>
              {/* Branch line */}
              <motion.line
                x1="40"
                y1={y}
                x2="200"
                y2="100"
                stroke="rgba(255,255,255,0.15)"
                strokeWidth="1.5"
                strokeLinecap="round"
                initial={{ pathLength: 0, opacity: 0 }}
                animate={{
                  pathLength: phase >= 1 ? 1 : 0,
                  opacity: phase >= 1 ? 1 : 0,
                }}
                transition={{ duration: 0.8, delay: i * 0.25, ease }}
              />
              {/* Branch dot */}
              <motion.circle
                cx="40"
                cy={y}
                r="4"
                fill="rgba(255,255,255,0.1)"
                stroke="rgba(255,255,255,0.25)"
                strokeWidth="1"
                initial={{ opacity: 0, scale: 0 }}
                animate={{
                  opacity: phase >= 1 ? 1 : 0,
                  scale: phase >= 1 ? 1 : 0,
                }}
                transition={{ duration: 0.4, delay: i * 0.2, ease }}
              />
              {/* Branch label */}
              <motion.text
                x="10"
                y={y + 3}
                className="font-mono"
                fontSize="8"
                fill="rgba(255,255,255,0.3)"
                textAnchor="start"
                initial={{ opacity: 0 }}
                animate={{ opacity: phase >= 1 ? 1 : 0 }}
                transition={{ duration: 0.4, delay: i * 0.2 }}
              >
                {branchNames[i]}
              </motion.text>
            </g>
          );
        })}

        {/* Merge circle */}
        <motion.circle
          cx="200"
          cy="100"
          r="10"
          fill="rgba(52,211,153,0.1)"
          stroke="rgba(52,211,153,0.4)"
          strokeWidth="1.5"
          initial={{ opacity: 0, scale: 0 }}
          animate={{
            opacity: phase >= 2 ? 1 : 0,
            scale: phase >= 2 ? 1 : 0,
          }}
          transition={{ duration: 0.5, ease }}
        />
        <motion.text
          x="200"
          y="103"
          fontSize="7"
          fill="rgba(52,211,153,0.6)"
          textAnchor="middle"
          initial={{ opacity: 0 }}
          animate={{ opacity: phase >= 2 ? 1 : 0 }}
          transition={{ duration: 0.4, delay: 0.2 }}
        >
          merge
        </motion.text>

        {/* Merge glow */}
        {phase >= 2 && (
          <motion.circle
            cx="200"
            cy="100"
            r="10"
            fill="none"
            stroke="rgba(52,211,153,0.3)"
            strokeWidth="2"
            initial={{ r: 10, opacity: 0.6 }}
            animate={{ r: 20, opacity: 0 }}
            transition={{ duration: 1.2, ease }}
          />
        )}

        {/* Trunk line */}
        <motion.line
          x1="210"
          y1="100"
          x2="320"
          y2="100"
          stroke="rgba(52,211,153,0.25)"
          strokeWidth="2"
          strokeLinecap="round"
          initial={{ pathLength: 0, opacity: 0 }}
          animate={{
            pathLength: phase >= 3 ? 1 : 0,
            opacity: phase >= 3 ? 1 : 0,
          }}
          transition={{ duration: 0.8, ease }}
        />
        <motion.text
          x="265"
          y="93"
          fontSize="8"
          fill="rgba(255,255,255,0.25)"
          textAnchor="middle"
          className="font-mono"
          initial={{ opacity: 0 }}
          animate={{ opacity: phase >= 3 ? 1 : 0 }}
          transition={{ duration: 0.4, delay: 0.3 }}
        >
          main
        </motion.text>

        {/* Production checkmark */}
        <motion.circle
          cx="340"
          cy="100"
          r="14"
          fill="rgba(52,211,153,0.1)"
          stroke="rgba(52,211,153,0.4)"
          strokeWidth="1.5"
          initial={{ opacity: 0, scale: 0 }}
          animate={{
            opacity: phase >= 4 ? 1 : 0,
            scale: phase >= 4 ? 1 : 0,
          }}
          transition={{ duration: 0.5, ease }}
        />
        <motion.path
          d="M332 100 L338 106 L350 94"
          stroke="rgba(52,211,153,0.7)"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          fill="none"
          initial={{ pathLength: 0, opacity: 0 }}
          animate={{
            pathLength: phase >= 4 ? 1 : 0,
            opacity: phase >= 4 ? 1 : 0,
          }}
          transition={{ duration: 0.5, delay: 0.3, ease }}
        />
        <motion.text
          x="340"
          y="122"
          fontSize="7"
          fill="rgba(52,211,153,0.5)"
          textAnchor="middle"
          initial={{ opacity: 0 }}
          animate={{ opacity: phase >= 4 ? 1 : 0 }}
          transition={{ duration: 0.4, delay: 0.5 }}
        >
          production
        </motion.text>
      </svg>
    </div>
  );
}

/* ─── View components map ─── */
const viewComponents: Record<
  TabId,
  React.ComponentType<{ animationKey: number }>
> = {
  p0: P0View,
  l1: L1View,
  l2: L2View,
  l3: L3View,
  main: MainView,
};

/* ─── LayerExplorer ─── */
export function LayerExplorer() {
  const [activeTab, setActiveTab] = useState<TabId>("p0");
  const [animationKey, setAnimationKey] = useState(0);
  const pausedUntilRef = useRef(0);
  const sectionRef = useRef<HTMLDivElement>(null);
  const inView = useInView(sectionRef, { once: false, margin: "-100px" });

  /* Auto-cycle tabs */
  useEffect(() => {
    if (!inView) return;

    const interval = setInterval(() => {
      if (Date.now() < pausedUntilRef.current) return;

      setActiveTab((prev) => {
        const idx = tabs.findIndex((t) => t.id === prev);
        const next = tabs[(idx + 1) % tabs.length].id;
        return next;
      });
      setAnimationKey((k) => k + 1);
    }, AUTO_CYCLE_MS);

    return () => clearInterval(interval);
  }, [inView]);

  const handleTabClick = useCallback(
    (id: TabId) => {
      if (id === activeTab) return;
      pausedUntilRef.current = Date.now() + PAUSE_AFTER_CLICK_MS;
      setActiveTab(id);
      setAnimationKey((k) => k + 1);
    },
    [activeTab],
  );

  const ActiveView = viewComponents[activeTab];
  const activeTabDef = tabs.find((t) => t.id === activeTab)!;

  return (
    <section
      id="pipeline"
      ref={sectionRef}
      className="relative z-10 py-28 px-6"
    >
      <div className="mx-auto max-w-4xl">
        <BlurFade>
          {/* Eyebrow */}
          <p className="font-mono text-xs uppercase tracking-widest text-white/35 mb-4">
            How it works
          </p>

          {/* Headline */}
          <h2 className="text-3xl sm:text-4xl font-semibold tracking-tight mb-10">
            Watch the pipeline work
          </h2>
        </BlurFade>

        <BlurFade delay={0.15}>
          {/* Tab bar */}
          <div className="flex gap-2 mb-4 overflow-x-auto">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => handleTabClick(tab.id)}
                className={`px-4 py-2 font-mono text-xs uppercase tracking-wider rounded-t-md transition-colors duration-300 shrink-0 ${
                  activeTab === tab.id
                    ? "text-white/90 border-b-2 border-white/40 bg-white/[0.04]"
                    : "text-white/35 border-b-2 border-transparent hover:text-white/55 hover:bg-white/[0.02]"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Viewport */}
          <div className="glass-panel relative overflow-hidden" style={{ minHeight: 300 }}>
            <AnimatePresence mode="wait">
              <motion.div
                key={`${activeTab}-${animationKey}`}
                className="w-full"
                style={{ minHeight: 300 }}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.3 }}
              >
                <ActiveView animationKey={animationKey} />
              </motion.div>
            </AnimatePresence>
          </div>

          {/* Description */}
          <AnimatePresence mode="wait">
            <motion.p
              key={activeTab}
              className="mt-5 text-sm text-white/45 leading-relaxed max-w-2xl"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.35, ease }}
            >
              {activeTabDef.description}
            </motion.p>
          </AnimatePresence>
        </BlurFade>
      </div>
    </section>
  );
}
