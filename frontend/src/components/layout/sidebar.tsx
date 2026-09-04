"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

interface NavItem {
  label: string;
  href: string;
  icon: string;
}

const navItems: NavItem[] = [
  { label: "Overview", href: "/", icon: "◉" },
  { label: "Transactions", href: "/transactions", icon: "⚡" },
  { label: "Agents", href: "/agents", icon: "🤖" },
  { label: "Policies", href: "/policies", icon: "📋" },
  { label: "Risk Intelligence", href: "/risk-intelligence", icon: "🛡" },
  { label: "Audit Vault", href: "/audit-vault", icon: "🔒" },
  { label: "Calibration", href: "/calibration", icon: "📊" },
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
              href={item.href}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                isActive
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              }`}
            >
              <span className="text-base">{item.icon}</span>
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="px-6 py-4 border-t border-border">
        <p className="text-[10px] text-muted-foreground/50 uppercase tracking-wider">
          Transaction Twin v1.0
        </p>
      </div>
    </aside>
  );
}
