"use client";

import { StatusIndicator } from "@/components/ui/status-indicator";

export function Header() {
  return (
    <header className="flex items-center justify-between border-b border-border bg-card px-6 py-4">
      <div className="flex items-center gap-3">
        <span className="md:hidden text-xl">◈</span>
        <h1 className="text-lg font-semibold">Transaction Twin</h1>
      </div>

      <div className="flex items-center gap-4">
        <StatusIndicator status="ok" label="System operational" />
      </div>
    </header>
  );
}
