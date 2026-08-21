import { type HTMLAttributes, forwardRef } from "react";

type Status = "ok" | "warning" | "error" | "inactive";

interface StatusIndicatorProps extends HTMLAttributes<HTMLSpanElement> {
  status: Status;
  label?: string;
}

const statusClasses: Record<Status, string> = {
  ok: "bg-success",
  warning: "bg-warning",
  error: "bg-destructive",
  inactive: "bg-muted-foreground",
};

export const StatusIndicator = forwardRef<HTMLSpanElement, StatusIndicatorProps>(
  ({ status, label, className = "", ...props }, ref) => {
    return (
      <span ref={ref} className={`inline-flex items-center gap-2 ${className}`} {...props}>
        <span className={`h-2 w-2 rounded-full ${statusClasses[status]}`} />
        {label && <span className="text-sm text-muted-foreground">{label}</span>}
      </span>
    );
  }
);

StatusIndicator.displayName = "StatusIndicator";
