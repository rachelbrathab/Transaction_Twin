"use client";

import { useRouter } from "next/navigation";
import { clearStoredToken, isAuthenticated } from "@/lib/api";
import { StatusIndicator } from "@/components/ui/status-indicator";

export function Header() {
  const router = useRouter();
  const authed = isAuthenticated();

  function handleLogout() {
    clearStoredToken();
    router.push("/login");
  }

  return (
    <header className="flex items-center justify-between border-b border-border bg-card px-6 py-4">
      <div className="flex items-center gap-3">
        <span className="md:hidden text-xl">◈</span>
        <h1 className="text-lg font-semibold">Transaction Twin</h1>
      </div>

      <div className="flex items-center gap-4">
        <StatusIndicator status="ok" label="System operational" />
        {authed && (
          <button
            onClick={handleLogout}
            className="text-xs text-muted-foreground hover:text-foreground transition-colors px-2 py-1 rounded border border-border"
          >
            Sign Out
          </button>
        )}
      </div>
    </header>
  );
}
