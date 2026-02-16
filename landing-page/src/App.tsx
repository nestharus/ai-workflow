import { WebGLBackground } from "@/components/WebGLBackground";
import { GrainOverlay } from "@/components/GrainOverlay";
import { Navbar } from "@/components/Navbar";
import { Hero } from "@/components/Hero";
import { ProblemSection } from "@/components/ProblemSection";
import { LayerExplorer } from "@/components/LayerExplorer";
import { FeaturesSection } from "@/components/FeaturesSection";
import { ReviewSection } from "@/components/ReviewSection";
import { DifferentiatorSection } from "@/components/DifferentiatorSection";
import { PricingSection } from "@/components/PricingSection";
import { FAQSection } from "@/components/FAQSection";
import { WaitlistSection } from "@/components/WaitlistSection";
import { Footer } from "@/components/Footer";

export default function App() {
  return (
    <>
      <WebGLBackground />
      <GrainOverlay />
      <Navbar />
      <Hero />
      <ProblemSection />
      <LayerExplorer />
      <FeaturesSection />
      <ReviewSection />
      <DifferentiatorSection />
      <PricingSection />
      <FAQSection />
      <WaitlistSection />
      <Footer />
    </>
  );
}
