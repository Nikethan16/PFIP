"use client";

import * as React from "react";
import { AlertTriangle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/toast";

/**
 * Global error boundary. Catches render-time errors in the React tree and
 * shows a friendly fallback. Also surfaces a toast so that transient failures
 * from mutations are visible even when the component handles them internally.
 */
interface ErrorBoundaryProps {
  children: React.ReactNode;
  fallback?: (error: Error, reset: () => void) => React.ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

export class ErrorBoundary extends React.Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  override state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  override componentDidCatch(error: Error, info: React.ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error("[ErrorBoundary]", error, info);
    try {
      toast.error(error.message || "Something broke. See console.");
    } catch {
      // Toast not mounted yet on very early failures; fine to swallow.
    }
  }

  reset = () => this.setState({ error: null });

  override render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    if (this.props.fallback) return this.props.fallback(error, this.reset);
    return (
      <div
        className="m-4 rounded-lg border border-destructive/40 bg-destructive/5 p-6 text-sm"
        role="alert"
      >
        <div className="mb-2 flex items-center gap-2 font-semibold text-destructive">
          <AlertTriangle className="h-4 w-4" />
          Something broke in the UI
        </div>
        <pre className="mb-3 max-h-40 overflow-auto whitespace-pre-wrap rounded bg-background p-2 text-xs">
          {error.message}
        </pre>
        <Button size="sm" variant="outline" onClick={this.reset}>
          Try again
        </Button>
      </div>
    );
  }
}
