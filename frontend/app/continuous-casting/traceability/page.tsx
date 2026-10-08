import { Suspense } from "react";
import { AppShell } from "@/app/components/layout/AppShell";
import TraceabilityContent from "./TraceabilityContent";

export default function ContinuousCastingTraceabilityPage() {
  return (
    <AppShell>
      <Suspense fallback={null}>
        <TraceabilityContent />
      </Suspense>
    </AppShell>
  );
}
