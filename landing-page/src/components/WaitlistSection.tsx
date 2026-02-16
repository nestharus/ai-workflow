import { useState, type FormEvent } from "react";
import { BlurFade } from "@/components/ui/BlurFade";
import { ShimmerButton } from "@/components/ui/ShimmerButton";

export function WaitlistSection() {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [message, setMessage] = useState("");

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!email) return;

    setStatus("loading");
    setMessage("");

    try {
      const res = await fetch("/api/waitlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });

      if (res.ok) {
        setStatus("success");
        setMessage("You're on the list. We'll be in touch.");
        setEmail("");
      } else {
        setStatus("error");
        setMessage("Something went wrong. Please try again.");
      }
    } catch {
      setStatus("error");
      setMessage("Something went wrong. Please try again.");
    }
  }

  return (
    <section id="waitlist-final" className="relative z-10 py-28 px-6">
      <div className="mx-auto max-w-2xl text-center">
        <BlurFade>
          <p className="font-mono text-xs uppercase tracking-widest text-white/35 mb-4">
            Get started
          </p>
          <h2 className="text-3xl sm:text-4xl font-semibold tracking-tight mb-4">
            Ready to ship code you can trust?
          </h2>
          <p className="text-lg text-white/55 mb-10">
            Your AI writes the code. Oulipoly Automaton checks if it's right.
          </p>
        </BlurFade>

        <BlurFade delay={0.15}>
          <form
            onSubmit={handleSubmit}
            className="flex flex-col sm:flex-row items-center gap-3 justify-center"
          >
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
              required
              className="glass-panel w-full sm:w-80 rounded-lg px-4 py-2.5 text-sm text-white/80 placeholder:text-white/25 outline-none focus:border-white/[0.2] bg-transparent"
            />
            <ShimmerButton
              onClick={(e) => {
                e.preventDefault();
                handleSubmit(e as unknown as FormEvent);
              }}
              size="default"
            >
              {status === "loading" ? "Joining..." : "Join Waitlist"}
            </ShimmerButton>
          </form>

          {/* Status message */}
          {message && (
            <p
              className={`mt-4 text-sm ${
                status === "success" ? "text-green-400/70" : "text-red-400/70"
              }`}
            >
              {message}
            </p>
          )}

          <p className="mt-6 text-xs text-white/25">
            Free to start. No credit card required.
          </p>
        </BlurFade>
      </div>
    </section>
  );
}
