import type { ReactNode, AnchorHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

interface ShimmerButtonProps extends AnchorHTMLAttributes<HTMLAnchorElement> {
  children: ReactNode;
  size?: "default" | "lg";
}

export function ShimmerButton({ children, className, size = "default", ...props }: ShimmerButtonProps) {
  return (
    <a
      className={cn(
        "group relative inline-flex items-center justify-center overflow-hidden rounded-lg",
        "border border-white/[0.12] bg-white/[0.06]",
        "font-medium tracking-wide text-white/90",
        "transition-all duration-300 hover:border-white/[0.2] hover:bg-white/[0.1]",
        "hover:shadow-[0_0_20px_rgba(255,255,255,0.08)]",
        size === "lg" ? "px-8 py-3.5 text-base" : "px-5 py-2.5 text-sm",
        className,
      )}
      {...props}
    >
      {/* Shimmer sweep */}
      <div className="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/[0.06] to-transparent group-hover:animate-[shimmer_2s_ease-in-out_infinite]" />
      <span className="relative z-10">{children}</span>
    </a>
  );
}
