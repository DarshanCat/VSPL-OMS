"use client";
import React, { Suspense } from "react";
import { AppShell } from "@/app/components/layout/AppShell";
import { MovePartsContent } from "./MovePartsContent";

export default function MovePartsPage() {
  return (
    <AppShell>
      <Suspense fallback={null}>
        <MovePartsContent />
      </Suspense>
    </AppShell>
  );
}
