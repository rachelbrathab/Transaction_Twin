"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

interface NavItem {
  label: string;
  href: string;
  icon: string;
  disabled?: boolean;
}

const navItems: NavItem[] = [
  { label: "Overview", href: "/", icon: "◉" },
  { label: "Transactions", href: "/transactions", icon: "⚡", disabled: true },
  { label: "Agents", href: "/agents", icon: "🤖", disabled: true },
  { label: "Policies", href: "/policies", icon: "📋", disabled: true },
  { label: "Risk Intelligence", href: "/risk", icon: "🛡", disabled: true },
  { label: "Audit Vault", href: "/audit", icon: "🔒", disabled: true },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="hidden md:flex w-64 flex-col border-r border-border bg-card">
      <div className="flex items-center gap-2 px-6 py-5 border-b border-border">
        <span className="text-xl">◈</span>
        <span className="font-semibold text-lg tracking-tight">Transaction Twin</span>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-1">
        {navItems.map((item) => {
          const isActive = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.disabled ? "#" : item.href}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                item.disabled
                  ? "text-muted-foreground/50 cursor-not-allowed"
                  : isActive
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
              }`}
            >
              <span className="text-base">{item.icon}</span>
              {item.label}
              {item.disabled && (
                <span className="ml-auto text-[10px] text-muted-foreground/50 uppercase tracking-wider">Soon</span>
              )}
            </Link>
          );
        })}
      </nav>

      <div className="px-6 py-4 border-t border-border">
        <p className="text-[10px] text-muted-foreground/50 uppercase tracking-wider">
          Sprint 1 — Foundation
        </p>
      </div>
    </aside>
  );
}
