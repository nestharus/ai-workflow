export function Footer() {
  return (
    <footer className="relative z-10 border-t border-white/[0.07] py-12">
      <div className="mx-auto flex max-w-6xl flex-col items-center gap-4 px-6 text-center">
        <div className="font-mono text-sm tracking-wider text-white/50">
          Oulipoly Automaton
        </div>
        <p className="text-sm text-white/30">
          Built by Oulipoly
        </p>
        <a
          href="mailto:contact@oulipoly.ai?subject=Oulipoly%20Automaton%20%E2%80%93%20Inquiry"
          className="text-sm text-white/30 hover:text-white/50 transition-colors"
        >
          Contact us
        </a>
        <p className="text-xs text-white/20">
          &copy; 2026 Oulipoly Automaton. All rights reserved.
        </p>
      </div>
    </footer>
  );
}
