"use client";

import { AppShell } from "@/components/layout/app-shell";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { Badge } from "@/components/ui/badge";

const stats = [
  { label: "System Status", value: "Operational", status: "ok" as const },
  { label: "Transactions", value: "—", status: "inactive" as const },
  { label: "Active Agents", value: "—", status: "inactive" as const },
  { label: "Risk Alerts", value: "—", status: "inactive" as const },
];

const futureModules = [
  { name: "Intent Engine", description: "Natural-language user intent extraction", status: "planned" },
  { name: "Transaction Twin", description: "Expected transaction state tracking", status: "planned" },
  { name: "Risk Engine", description: "ML-based risk scoring", status: "planned" },
  { name: "Policy Engine", description: "Deterministic policy enforcement", status: "planned" },
  { name: "Agent Simulator", description: "Synthetic agent behavior simulation", status: "planned" },
  { name: "Razorpay Integration", description: "Test mode payment processing", status: "planned" },
];

export default function HomePage() {
  return (
    <AppShell>
      <div className="space-y-6">
        {/* Page Header */}
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Overview</h2>
          <p className="text-muted-foreground mt-1">
            Transaction Twin — The Trust Layer for AI Payments
          </p>
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {stats.map((stat) => (
            <Card key={stat.label}>
              <CardContent className="pt-6">
                <p className="text-sm text-muted-foreground">{stat.label}</p>
                <div className="flex items-center gap-2 mt-1">
                  <StatusIndicator status={stat.status} />
                  <span className="text-2xl font-bold">{stat.value}</span>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        {/* Architecture Overview */}
        <Card>
          <CardHeader>
            <CardTitle>System Architecture</CardTitle>
            <CardDescription>
              The end-to-end flow for AI-initiated payment risk control
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              {[
                "User Intent",
                "Agent Identity",
                "Agent Actions",
                "Transaction",
                "Policy",
                "Risk",
                "Decision",
              ].map((step, i) => (
                <span key={step} className="flex items-center gap-2">
                  <Badge variant={i === 6 ? "success" : "outline"}>{step}</Badge>
                  {i < 6 && <span className="text-muted-foreground">→</span>}
                </span>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Future Modules */}
        <Card>
          <CardHeader>
            <CardTitle>Modules</CardTitle>
            <CardDescription>
              Planned components — coming in future sprints
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {futureModules.map((mod) => (
                <div
                  key={mod.name}
                  className="rounded-lg border border-border p-4 opacity-60"
                >
                  <div className="flex items-center justify-between">
                    <h4 className="font-medium text-sm">{mod.name}</h4>
                    <Badge variant="default">Sprint 2+</Badge>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">
                    {mod.description}
                  </p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}
