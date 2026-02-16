import { useState, useEffect } from "react";
import { cn } from "@/lib/utils";
import { ShimmerButton } from "@/components/ui/ShimmerButton";

export function Navbar() {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    function onScroll() {
      setScrolled(window.scrollY > 50);
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <nav
      className={cn(
        "fixed top-0 left-0 right-0 z-50 transition-all duration-300",
        scrolled
          ? "bg-[#060a12]/80 backdrop-blur-xl border-b border-white/[0.07]"
          : "bg-transparent border-b border-transparent",
      )}
    >
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
        {/* Logo */}
        <div className="flex items-baseline gap-1.5">
          <span className="text-lg font-semibold tracking-tight text-white/90">
            Oulipoly
          </span>
          <span className="text-lg font-normal tracking-tight text-white/40">
            Automaton
          </span>
        </div>

        {/* CTA */}
        <ShimmerButton href="#waitlist-final">Join Waitlist</ShimmerButton>
      </div>
    </nav>
  );
}
