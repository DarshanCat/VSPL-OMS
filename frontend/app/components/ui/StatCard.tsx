import React from "react";

interface StatCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon?: React.ReactNode;
  trend?: {
    value: string;
    isPositive?: boolean;
  };
  highlightColor?: "blue" | "emerald" | "amber" | "rose" | "purple";
  className?: string;
}

export function StatCard({
  title,
  value,
  subtitle,
  icon,
  trend,
  highlightColor = "blue",
  className = "",
}: StatCardProps) {
  const borderTopColors = {
    blue: "border-t-blue-500",
    emerald: "border-t-emerald-500",
    amber: "border-t-amber-500",
    rose: "border-t-rose-500",
    purple: "border-t-purple-500",
  };

  const iconBgColors = {
    blue: "bg-blue-50 text-blue-600 dark:bg-blue-950/50 dark:text-blue-400",
    emerald: "bg-emerald-50 text-emerald-600 dark:bg-emerald-950/50 dark:text-emerald-400",
    amber: "bg-amber-50 text-amber-600 dark:bg-amber-950/50 dark:text-amber-400",
    rose: "bg-rose-50 text-rose-600 dark:bg-rose-950/50 dark:text-rose-400",
    purple: "bg-purple-50 text-purple-600 dark:bg-purple-950/50 dark:text-purple-400",
  };

  return (
    <div
      className={`relative overflow-hidden rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-sm transition-all hover:shadow-md border-t-4 ${borderTopColors[highlightColor]} ${className}`}
    >
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
            {title}
          </p>
          <h3 className="mt-2 text-2xl font-bold tracking-tight text-zinc-900 dark:text-zinc-50">
            {value}
          </h3>
          {subtitle && (
            <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
              {subtitle}
            </p>
          )}
          {trend && (
            <div className="mt-2 flex items-center gap-1 text-xs font-medium">
              <span
                className={
                  trend.isPositive
                    ? "text-emerald-600 dark:text-emerald-400"
                    : "text-rose-600 dark:text-rose-400"
                }
              >
                {trend.value}
              </span>
              <span className="text-zinc-400">vs yesterday</span>
            </div>
          )}
        </div>
        {icon && (
          <div className={`flex h-11 w-11 items-center justify-center rounded-xl ${iconBgColors[highlightColor]}`}>
            {icon}
          </div>
        )}
      </div>
    </div>
  );
}
