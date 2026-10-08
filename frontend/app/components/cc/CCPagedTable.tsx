"use client";
import React from "react";
import { CCErrorBanner } from "./CCErrorBanner";

export interface CCColumn<T> {
  header: string;
  render: (row: T) => React.ReactNode;
  className?: string;
}

// Renders one backend page ({items,total,limit,offset}); paging is offset based, exactly as the API.
export function CCPagedTable<T>({
  columns,
  items,
  total,
  limit,
  offset,
  onPageChange,
  rowKey,
  loading = false,
  error,
  emptyText = "No records.",
  hidePager = false,
}: {
  columns: CCColumn<T>[];
  items: T[];
  total: number;
  limit: number;
  offset: number;
  onPageChange: (nextOffset: number) => void;
  rowKey: (row: T) => string;
  loading?: boolean;
  error?: string | null;
  emptyText?: string;
  hidePager?: boolean; // for lists that are a fixed, backend-capped excerpt (the caller shows its own caption)
}) {
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + items.length, total);
  return (
    <div className="space-y-2">
      <CCErrorBanner message={error} />
      <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
        <table className="w-full text-xs">
          <thead className="bg-zinc-50 text-left text-zinc-500 dark:bg-zinc-800/50">
            <tr>
              {columns.map((c) => (
                <th key={c.header} className={`whitespace-nowrap px-3 py-2 font-semibold ${c.className ?? ""}`}>
                  {c.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {items.map((row) => (
              <tr key={rowKey(row)} className="hover:bg-zinc-50 dark:hover:bg-zinc-800/30">
                {columns.map((c) => (
                  <td key={c.header} className={`px-3 py-1.5 ${c.className ?? ""}`}>
                    {c.render(row)}
                  </td>
                ))}
              </tr>
            ))}
            {items.length === 0 && (
              <tr>
                <td colSpan={columns.length} className="px-3 py-6 text-center text-zinc-400">
                  {loading ? "Loading..." : emptyText}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {!hidePager && (
        <div className="flex items-center justify-between text-xs text-zinc-500">
          <span>
            Showing {from}-{to} of {total}
          </span>
          <span className="flex gap-1">
            <button
              type="button"
              disabled={loading || offset <= 0}
              onClick={() => onPageChange(Math.max(0, offset - limit))}
              className="rounded-md border border-zinc-300 px-2 py-1 disabled:opacity-40 dark:border-zinc-700"
            >
              Prev
            </button>
            <button
              type="button"
              disabled={loading || offset + limit >= total}
              onClick={() => onPageChange(offset + limit)}
              className="rounded-md border border-zinc-300 px-2 py-1 disabled:opacity-40 dark:border-zinc-700"
            >
              Next
            </button>
          </span>
        </div>
      )}
    </div>
  );
}
