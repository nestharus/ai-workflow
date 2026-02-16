import { cn } from "@/lib/utils";

interface BorderBeamProps {
  className?: string;
  size?: number;
  duration?: number;
  delay?: number;
  colorFrom?: string;
  colorTo?: string;
}

export function BorderBeam({
  className,
  size = 200,
  duration = 12,
  delay = 0,
  colorFrom = "rgba(255,255,255,0.3)",
  colorTo = "rgba(255,255,255,0)",
}: BorderBeamProps) {
  return (
    <div
      className={cn(
        "pointer-events-none absolute inset-0 rounded-[inherit]",
        className,
      )}
      style={{
        maskImage: `conic-gradient(from calc(var(--beam-angle) - ${size / 2}deg) at 50% 50%, transparent 0%, #000 ${size}deg, transparent ${size}deg)`,
        WebkitMaskImage: `conic-gradient(from calc(var(--beam-angle) - ${size / 2}deg) at 50% 50%, transparent 0%, #000 ${size}deg, transparent ${size}deg)`,
        background: `linear-gradient(${colorFrom}, ${colorTo})`,
        animation: `border-beam-spin ${duration}s linear ${delay}s infinite`,
      }}
    />
  );
}
