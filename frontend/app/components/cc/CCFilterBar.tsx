import React from "react";

// Layout row for list filters; the screen supplies the inputs. Dense, wraps on narrow widths.
export function CCFilterBar({ children, onClear }: { children: React.ReactNode; onClear?: () => void }) {
  return (
    <div className="flex flex-wrap items-end gap-2 rounded-lg border border-zinc-200 bg-white p-2 text-xs dark:border-zinc-800 dark:bg-zinc-900">
      {children}
      {onClear && (
        <button
          type="button"
          onClick={onClear}
          className="rounded-md border border-zinc-300 px-2 py-1 hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
        >
          Clear
        </button>
      )}
    </div>
  );
}
