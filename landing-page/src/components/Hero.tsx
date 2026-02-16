import { useEffect, useRef, useState, useCallback } from "react";
import { BlurFade } from "@/components/ui/BlurFade";
import { ShimmerButton } from "@/components/ui/ShimmerButton";

/* ─── Isometric layer data ─── */
const layers = [
  { id: "P0", label: "Discovery", tint: "rgba(148,163,184,0.1)" },
  { id: "L1", label: "Build", tint: "rgba(255,255,255,0.10)" },
  { id: "L2", label: "Architecture", tint: "rgba(255,255,255,0.12)" },
  { id: "L3", label: "Quality", tint: "rgba(255,255,255,0.14)" },
  { id: "Main", label: "Production", tint: "rgba(52,211,153,0.15)" },
] as const;

/* ─── Layer-aware particle system ─── */
interface LayerPos {
  x: number;
  y: number;
  w: number;
}

interface Particle {
  x: number;
  y: number;
  targetLayer: number;
  currentLayer: number;
  isDemotion: boolean;
  speed: number;
  pauseTimer: number;
  pauseDuration: number;
  life: number;
  size: number;
  trail: { x: number; y: number }[];
  done: boolean;
}

function useParticleCanvas(
  canvasRef: React.RefObject<HTMLCanvasElement | null>,
  stackRef: React.RefObject<HTMLDivElement | null>,
) {
  useEffect(() => {
    const canvas = canvasRef.current;
    const stackEl = stackRef.current;
    if (!canvas || !stackEl) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let raf: number;
    let lastSpawn = 0;
    const particles: Particle[] = [];
    let layerPositions: LayerPos[] = [];
    let W = 0;
    let H = 0;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);

    function updateLayerPositions() {
      const panels = stackEl!.querySelectorAll("[data-layer-panel]");
      const stackRect = stackEl!.getBoundingClientRect();
      layerPositions = [];
      panels.forEach((panel) => {
        const r = panel.getBoundingClientRect();
        layerPositions.push({
          x: r.left - stackRect.left + r.width * 0.5,
          y: r.top - stackRect.top + r.height * 0.5,
          w: r.width,
        });
      });
    }

    function resize() {
      if (!canvas || !stackEl) return;
      const rect = stackEl.getBoundingClientRect();
      W = rect.width;
      H = rect.height;
      canvas.width = W * dpr;
      canvas.height = H * dpr;
      canvas.style.width = W + "px";
      canvas.style.height = H + "px";
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
      updateLayerPositions();
    }

    function spawnParticle(): Particle | null {
      if (layerPositions.length < 5) return null;
      const isDemotion = Math.random() < 0.2;
      const startLayer = isDemotion ? 2 + Math.floor(Math.random() * 3) : 0;
      const startPos = layerPositions[startLayer] || layerPositions[0];
      return {
        x: startPos.x + (Math.random() - 0.5) * startPos.w * 0.6,
        y: startPos.y,
        targetLayer: isDemotion ? 1 : 4,
        currentLayer: startLayer,
        isDemotion,
        speed: isDemotion ? 80 : 40,
        pauseTimer: 0,
        pauseDuration: 300 + Math.random() * 400,
        life: 1.0,
        size: 2 + Math.random() * 1.5,
        trail: [],
        done: false,
      };
    }

    function tick(now: number) {
      if (!canvas || !ctx) return;
      ctx.clearRect(0, 0, W, H);

      // Spawn
      if (now - lastSpawn > 500 && particles.length < 20) {
        const np = spawnParticle();
        if (np) particles.push(np);
        lastSpawn = now;
      }

      for (let i = particles.length - 1; i >= 0; i--) {
        const p = particles[i];
        if (p.done) {
          p.life -= 0.02;
          if (p.life <= 0) {
            particles.splice(i, 1);
            continue;
          }
        }

        if (layerPositions.length < 5) continue;

        // Store trail
        p.trail.unshift({ x: p.x, y: p.y });
        if (p.trail.length > 3) p.trail.pop();

        if (!p.done) {
          const target = layerPositions[p.currentLayer];
          if (!target) continue;

          const dy = Math.abs(p.y - target.y);
          if (dy < 3) {
            // At a layer — pause then advance
            if (p.pauseTimer < p.pauseDuration) {
              p.pauseTimer += 16;
            } else {
              p.pauseTimer = 0;
              p.pauseDuration = 200 + Math.random() * 300;
              if (p.isDemotion) {
                if (p.currentLayer > p.targetLayer) {
                  p.currentLayer--;
                } else {
                  p.isDemotion = false;
                  p.speed = 40;
                  p.targetLayer = 4;
                }
              } else {
                if (p.currentLayer < p.targetLayer) {
                  p.currentLayer++;
                } else {
                  p.done = true;
                }
              }
            }
          } else {
            // Move toward current layer
            const direction = target.y < p.y ? -1 : 1;
            const moveSpeed = p.isDemotion ? p.speed * 1.5 : p.speed;
            p.y += direction * moveSpeed * 0.016;
            p.x += (Math.random() - 0.5) * 0.5;
          }
        }

        // Draw trail
        for (let t = p.trail.length - 1; t >= 0; t--) {
          const trailAlpha = p.life * (1 - t / 3) * 0.3;
          const trailSize = p.size * (1 - t / 3) * 0.6;
          if (trailAlpha <= 0) continue;
          ctx.globalAlpha = trailAlpha;
          ctx.fillStyle = p.isDemotion ? "#f87171" : "#c0c8d0";
          ctx.beginPath();
          ctx.arc(p.trail[t].x, p.trail[t].y, trailSize, 0, Math.PI * 2);
          ctx.fill();
        }

        // Draw particle
        ctx.globalAlpha = p.life;
        ctx.fillStyle = p.isDemotion ? "#f87171" : "#ffffff";
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        ctx.fill();

        // Glow
        ctx.globalAlpha = p.life * 0.2;
        const grad = ctx.createRadialGradient(
          p.x, p.y, 0, p.x, p.y, p.size * 3,
        );
        grad.addColorStop(
          0,
          p.isDemotion
            ? "rgba(248,113,113,0.4)"
            : "rgba(200,210,220,0.4)",
        );
        grad.addColorStop(1, "rgba(0,0,0,0)");
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size * 3, 0, Math.PI * 2);
        ctx.fill();
      }

      ctx.globalAlpha = 1;
      raf = requestAnimationFrame(tick);
    }

    window.addEventListener("resize", resize, { passive: true });

    // Wait for layout to settle before starting
    const startTimer = setTimeout(() => {
      resize();
      raf = requestAnimationFrame(tick);
    }, 500);

    return () => {
      clearTimeout(startTimer);
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
    };
  }, [canvasRef, stackRef]);
}

/* ─── Scroll indicator visibility ─── */
function useScrollFade() {
  const [visible, setVisible] = useState(true);
  useEffect(() => {
    function onScroll() {
      setVisible(window.scrollY < 100);
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  return visible;
}

/* ─── Hero component ─── */
export function Hero() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stackRef = useRef<HTMLDivElement>(null);
  useParticleCanvas(canvasRef, stackRef);
  const scrollVisible = useScrollFade();

  const scrollDown = useCallback(() => {
    const el = document.getElementById("problems");
    el?.scrollIntoView({ behavior: "smooth" });
  }, []);

  return (
    <section
      id="hero"
      className="relative z-10 min-h-screen flex items-center"
    >
      <div className="mx-auto w-full max-w-6xl px-6 py-24 grid grid-cols-1 lg:grid-cols-2 gap-16 items-center">
        {/* ── Left: copy ── */}
        <div className="flex flex-col gap-6">
          <BlurFade delay={0}>
            <p className="font-mono text-xs uppercase tracking-widest text-white/35">
              Prototype driven development
            </p>
          </BlurFade>

          <BlurFade delay={0.1}>
            <h1 className="text-[3.5rem] leading-[4rem] font-semibold tracking-tight">
              Code earns its way to{" "}
              <span className="font-serif italic text-white/95">
                production
              </span>
            </h1>
          </BlurFade>

          <BlurFade delay={0.2}>
            <p className="text-lg text-white/55 max-w-lg">
              Discovery and implementation happen in parallel. Your code moves
              through layered quality gates. When something is unclear, the
              system stops and asks.
            </p>
          </BlurFade>

          <BlurFade delay={0.3}>
            <ShimmerButton href="#pipeline" size="lg">
              See how it works
            </ShimmerButton>
          </BlurFade>

          <BlurFade delay={0.4}>
            <p className="text-xs text-white/25">
              Be first when we launch. No credit card needed.
            </p>
          </BlurFade>
        </div>

        {/* ── Right: isometric stack + particles ── */}
        <BlurFade delay={0.2} direction="right" className="relative">
          <div
            ref={stackRef}
            className="relative mx-auto"
            style={{ width: 400, height: 380 }}
          >
            <div
              className="relative"
              style={{
                perspective: "1200px",
                perspectiveOrigin: "50% 40%",
                width: 340,
                height: 340,
                margin: "0 auto",
              }}
            >
              {layers.map((layer, i) => {
                const isMain = layer.id === "Main";
                return (
                  <div
                    key={layer.id}
                    data-layer-panel
                    className="absolute"
                    style={{
                      width: 320,
                      height: 50,
                      left: "50%",
                      marginLeft: -160,
                      bottom: `${i * 60 + 10}px`,
                      transformStyle: "preserve-3d",
                      transform: `rotateX(60deg) rotateZ(-20deg) translateZ(${i * 2}px)`,
                    }}
                  >
                    <div
                      className="w-full h-full rounded-md relative overflow-hidden flex items-center justify-between px-4"
                      style={{
                        background: isMain
                          ? "linear-gradient(135deg, rgba(52,211,153,0.04) 0%, rgba(255,255,255,0.015) 100%)"
                          : "linear-gradient(135deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.015) 100%)",
                        border: `1px solid ${layer.tint}`,
                        boxShadow:
                          "0 0 1px rgba(255,255,255,0.12), 0 0 8px rgba(255,255,255,0.03), 0 4px 20px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.08)",
                      }}
                    >
                      {/* grid pattern */}
                      <div
                        className="absolute inset-0 pointer-events-none"
                        style={{
                          backgroundImage:
                            "linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px)",
                          backgroundSize: "20px 20px",
                        }}
                      />
                      <span
                        className="relative z-10 font-mono text-[11px] font-medium uppercase tracking-widest"
                        style={{
                          color: isMain
                            ? "rgba(52,211,153,0.8)"
                            : "rgba(255,255,255,0.5)",
                        }}
                      >
                        {layer.id}
                      </span>
                      <span className="relative z-10 text-[11px] text-white/35">
                        {layer.label}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* particle canvas overlay */}
            <canvas
              ref={canvasRef}
              className="absolute inset-0 w-full h-full pointer-events-none"
              style={{ zIndex: 10 }}
            />
          </div>
        </BlurFade>
      </div>

      {/* ── Scroll indicator ── */}
      <button
        type="button"
        onClick={scrollDown}
        className="absolute bottom-8 left-1/2 -translate-x-1/2 flex flex-col items-center gap-1 transition-opacity duration-500"
        style={{ opacity: scrollVisible ? 1 : 0 }}
      >
        <svg
          width="20"
          height="20"
          viewBox="0 0 20 20"
          fill="none"
          className="text-white/30 animate-bounce"
        >
          <path
            d="M5 8l5 5 5-5"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <span className="text-[10px] uppercase tracking-widest text-white/25 font-mono">
          Scroll
        </span>
      </button>
    </section>
  );
}
