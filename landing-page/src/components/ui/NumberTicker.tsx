import { useEffect, useRef, useState } from "react";
import { useInView, animate } from "motion/react";

interface NumberTickerProps {
  value: number;
  suffix?: string;
  delay?: number;
  className?: string;
}

export function NumberTicker({ value, suffix = "%", delay = 0, className }: NumberTickerProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true });
  const [display, setDisplay] = useState(0);

  useEffect(() => {
    if (!inView) return;
    const timeout = setTimeout(() => {
      const controls = animate(0, value, {
        duration: 1.8,
        ease: [0.22, 1, 0.36, 1],
        onUpdate: (v) => setDisplay(Math.round(v)),
      });
      return () => controls.stop();
    }, delay * 1000);
    return () => clearTimeout(timeout);
  }, [inView, value, delay]);

  return (
    <span ref={ref} className={className}>
      {display}{suffix}
    </span>
  );
}
