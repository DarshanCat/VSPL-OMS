import React from "react";

export type BadgeVariant = "green" | "amber" | "red" | "blue" | "gray" | "purple" | "cyan";

interface BadgeProps {
  children: React.ReactNode;
  variant?: BadgeVariant;
  className?: string;
  size?: "sm" | "md";
}

export function Badge({ children, variant = "blue", className = "", size = "md" }: BadgeProps) {
  const variantStyles: Record<BadgeVariant, string> = {
    green: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20",
    amber: "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20",
    red: "bg-rose-500/10 text-rose-600 dark:text-rose-400 border-rose-500/20",
    blue: "bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/20",
    gray: "bg-zinc-500/10 text-zinc-600 dark:text-zinc-400 border-zinc-500/20",
    purple: "bg-purple-500/10 text-purple-600 dark:text-purple-400 border-purple-500/20",
    cyan: "bg-cyan-500/10 text-cyan-600 dark:text-cyan-400 border-cyan-500/20",
  };

  const sizeStyles = {
    sm: "px-2 py-0.5 text-xs font-semibold",
    md: "px-2.5 py-1 text-xs font-semibold",
  };

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border ${variantStyles[variant]} ${sizeStyles[size]} ${className}`}
    >
      {children}
    </span>
  );
}

export function getRAGVariant(status: string): BadgeVariant {
  const s = (status || "").toLowerCase();
  if (s.includes("green") || s.includes("completed") || s.includes("dispatched") || s.includes("on track") || s.includes("ready")) {
    return "green";
  }
  if (s.includes("amber") || s.includes("at risk") || s.includes("in-process") || s.includes("in_production") || s.includes("in-progress")) {
    return "amber";
  }
  if (s.includes("red") || s.includes("overdue") || s.includes("high risk") || s.includes("shortfall") || s.includes("yes")) {
    return "red";
  }
  if (s.includes("skip")) {
    return "gray";
  }
  return "blue";
}
