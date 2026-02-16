import { useState } from "react";
import { BlurFade } from "@/components/ui/BlurFade";

const faqs = [
  {
    q: "How is this different from an AI coding assistant?",
    a: "AI assistants give you one model that writes code for you to review. Oulipoly Automaton runs code through a pipeline of quality gates before it reaches your branch. You answer questions, not review code.",
  },
  {
    q: "Do I need to know how to code?",
    a: "No. You write specs in plain language. The system handles implementation and review.",
  },
  {
    q: "How do I review the code it produces?",
    a: "You don't review code directly. The system surfaces questions through an Intent Agent queue when it hits ambiguity.",
  },
  {
    q: "Does it work with my existing tools?",
    a: "Yes. The workflow engine integrates with existing AI coding tools and adds a quality pipeline on top of whatever you already use.",
  },
  {
    q: "Is my code private?",
    a: "The free local version never sends code anywhere except to the AI APIs you configure.",
  },
  {
    q: "When does it launch?",
    a: "We're building the prototype now. Join the waitlist to be first when we launch.",
  },
];

function FAQItem({ q, a, delay }: { q: string; a: string; delay: number }) {
  const [open, setOpen] = useState(false);

  return (
    <BlurFade delay={delay}>
      <div className="glass-panel rounded-xl overflow-hidden">
        <button
          type="button"
          className="flex w-full items-center justify-between gap-4 px-6 py-5 text-left"
          onClick={() => setOpen((prev) => !prev)}
          aria-expanded={open}
        >
          <span className="text-sm font-medium text-white/80">{q}</span>
          <svg
            width="16"
            height="16"
            viewBox="0 0 16 16"
            fill="none"
            className={`shrink-0 text-white/30 transition-transform duration-300 ${
              open ? "rotate-180" : ""
            }`}
          >
            <path
              d="M4 6l4 4 4-4"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
        <div
          className={`grid transition-all duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] ${
            open ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"
          }`}
        >
          <div className="overflow-hidden">
            <p className="px-6 pb-5 text-sm text-white/45 leading-relaxed">
              {a}
            </p>
          </div>
        </div>
      </div>
    </BlurFade>
  );
}

export function FAQSection() {
  return (
    <section id="faq" className="relative z-10 py-28 px-6">
      <div className="mx-auto max-w-3xl">
        <BlurFade>
          <p className="font-mono text-xs uppercase tracking-widest text-white/35 mb-4">
            FAQ
          </p>
          <h2 className="text-3xl sm:text-4xl font-semibold tracking-tight mb-12">
            Questions
          </h2>
        </BlurFade>

        <div className="flex flex-col gap-3">
          {faqs.map((faq, i) => (
            <FAQItem key={i} q={faq.q} a={faq.a} delay={i * 0.06} />
          ))}
        </div>
      </div>
    </section>
  );
}
