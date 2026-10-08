import { Suspense } from "react";
import { AppShell } from "@/app/components/layout/AppShell";
import StoresContent from "./StoresContent";

export default function ContinuousCastingStoresPage() {
  return (
    <AppShell>
      <Suspense fallback={null}>
        <StoresContent />
      </Suspense>
    </AppShell>
  );
}
