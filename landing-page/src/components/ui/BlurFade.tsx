import { useRef, type ReactNode } from "react";
import { motion, useInView } from "motion/react";

interface BlurFadeProps {
  children: ReactNode;
  className?: string;
  delay?: number;
  direction?: "up" | "down" | "left" | "right";
  offset?: number;
  once?: boolean;
}

export function BlurFade({
  children,
  className,
  delay = 0,
  direction = "up",
  offset = 24,
  once = true,
}: BlurFadeProps) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once, margin: "-20px" });

  const dirMap = {
    up: { y: offset },
    down: { y: -offset },
    left: { x: offset },
    right: { x: -offset },
  };

  return (
    <motion.div
      ref={ref}
      className={className}
      initial={{
        opacity: 0,
        filter: "blur(6px)",
        ...dirMap[direction],
      }}
      animate={inView ? { opacity: 1, filter: "blur(0px)", x: 0, y: 0 } : {}}
      transition={{
        duration: 0.7,
        delay,
        ease: [0.22, 1, 0.36, 1],
      }}
    >
      {children}
    </motion.div>
  );
}
