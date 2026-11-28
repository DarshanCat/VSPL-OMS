"use client";
import React, { useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

// The Customer Schedule Status dashboard now lives in the PO Master dashboard (Customer Schedule Status tab).
export default function ScheduleStatusMoved() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/masters/pos/order-status?tab=schedules");
  }, [router]);
  return (
    <div className="p-8 text-center text-sm text-zinc-500">
      The Customer Schedule Status dashboard is now part of the{" "}
      <Link href="/masters/pos/order-status?tab=schedules" className="font-bold text-blue-600">PO Master dashboard</Link>.
    </div>
  );
}
