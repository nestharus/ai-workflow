import { BlurFade } from "@/components/ui/BlurFade";
import { MagicCard } from "@/components/ui/MagicCard";
import { BorderBeam } from "@/components/ui/BorderBeam";

const plans = [
  {
    badge: "Available at launch",
    name: "Free (Local)",
    price: "$0",
    featured: false,
    features: [
      "Runs on your machine",
      "Full privacy",
      "Bring your own AI keys",
      "All quality gates and workflows",
    ],
  },
  {
    badge: "Coming soon",
    name: "Hybrid",
    price: "$15/mo",
    featured: true,
    features: [
      "Remote management",
      "Local execution",
      "Easier setup",
      "Use your AI subscriptions",
    ],
  },
  {
    badge: "Future",
    name: "Cloud",
    price: "TBD",
    featured: false,
    features: [
      "Fully managed",
      "Easiest experience",
      "No setup required",
      "AI keys and hosting included",
    ],
  },
] as const;

export function PricingSection() {
  return (
    <section id="pricing" className="relative z-10 py-28 px-6">
      <div className="mx-auto max-w-4xl">
        <BlurFade>
          <p className="font-mono text-xs uppercase tracking-widest text-white/35 mb-4 text-center">
            Pricing
          </p>
          <h2 className="text-3xl sm:text-4xl font-semibold tracking-tight mb-12 text-center">
            Start free. Scale when ready.
          </h2>
        </BlurFade>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {plans.map((plan, i) => (
            <BlurFade key={plan.name} delay={i * 0.1}>
              <MagicCard
                className={`relative h-full rounded-2xl p-6 flex flex-col ${
                  plan.featured ? "border-white/[0.14]" : ""
                }`}
              >
                {plan.featured && <BorderBeam size={150} duration={10} />}

                {/* Badge */}
                <span className="inline-block self-start rounded-full border border-white/[0.08] bg-white/[0.04] px-3 py-1 font-mono text-[10px] uppercase tracking-wider text-white/40 mb-4">
                  {plan.badge}
                </span>

                {/* Name */}
                <h3 className="text-lg font-semibold tracking-tight text-white/90 mb-1">
                  {plan.name}
                </h3>

                {/* Price */}
                <p className="text-3xl font-semibold tracking-tight text-white/85 mb-6">
                  {plan.price}
                </p>

                {/* Features */}
                <ul className="flex flex-col gap-3 mt-auto">
                  {plan.features.map((feature) => (
                    <li
                      key={feature}
                      className="flex items-start gap-2.5 text-sm text-white/50"
                    >
                      <svg
                        width="16"
                        height="16"
                        viewBox="0 0 16 16"
                        fill="none"
                        className="shrink-0 mt-0.5 text-white/30"
                      >
                        <path
                          d="M4 8.5L7 11.5L12 5"
                          stroke="currentColor"
                          strokeWidth="1.5"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                      {feature}
                    </li>
                  ))}
                </ul>
              </MagicCard>
            </BlurFade>
          ))}
        </div>
      </div>
    </section>
  );
}
