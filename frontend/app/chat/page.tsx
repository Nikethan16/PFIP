"use client";

import * as React from "react";
import { MessageSquare, Plus, Sparkles } from "lucide-react";

import { MessageStream } from "@/components/agent/message-stream";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/shared/page-header";
import { cn } from "@/lib/utils";

/**
 * Chat page. We give chat its own full-bleed surface (no inner card border)
 * so it feels like a dedicated workspace rather than a widget on a page.
 *
 * The "conversations" sidebar is a placeholder for now — the backend doesn't
 * yet expose persisted history, but the UI is ready for it. The local
 * `useAgentChat` hook persists the active conversation to localStorage so
 * reload-survival works today.
 */
export default function ChatPage() {
  return (
    <div className="flex h-[calc(100dvh-9rem)] flex-col md:h-[calc(100dvh-7rem)]">
      <PageHeader
        title="Chat"
        description="Ask PFIP anything. Responses cite the portfolio, knowledge base, and live news."
        flat
        actions={
          <Button variant="outline" size="sm" className="gap-1" disabled>
            <Plus className="h-3.5 w-3.5" />
            New chat
          </Button>
        }
      />

      <div className="flex min-h-0 flex-1 gap-3">
        <ConversationSidebar />
        <div className="flex min-w-0 flex-1 flex-col rounded-xl border bg-card">
          <MessageStream />
        </div>
      </div>
    </div>
  );
}

function ConversationSidebar() {
  // Placeholder list — real history goes here when the backend exposes
  // `/agent/conversations`. We keep one "Current session" entry that
  // surfaces the localStorage-backed thread.
  const conversations = [
    {
      id: "current",
      title: "Current session",
      preview: "Live conversation (stored locally).",
      active: true,
    },
  ];
  return (
    <aside className="hidden w-64 shrink-0 flex-col rounded-xl border bg-card md:flex">
      <div className="flex items-center justify-between border-b px-3 py-2.5">
        <div className="flex items-center gap-2 text-xs font-medium">
          <MessageSquare className="h-3.5 w-3.5 text-muted-foreground" />
          Conversations
        </div>
        <Button variant="ghost" size="icon" className="h-7 w-7" disabled>
          <Plus className="h-3.5 w-3.5" />
        </Button>
      </div>
      <ul className="flex-1 space-y-px overflow-y-auto p-2">
        {conversations.map((c) => (
          <li key={c.id}>
            <button
              type="button"
              className={cn(
                "block w-full rounded-md px-2 py-2 text-left transition-colors",
                c.active
                  ? "bg-accent text-accent-foreground"
                  : "hover:bg-accent/60",
              )}
            >
              <div className="flex items-center gap-1.5 text-xs font-medium">
                <Sparkles className="h-3 w-3 text-primary" />
                <span className="truncate">{c.title}</span>
              </div>
              <div className="mt-0.5 truncate text-[11px] text-muted-foreground">
                {c.preview}
              </div>
            </button>
          </li>
        ))}
        <li className="px-2 pt-3">
          <Skeleton className="mb-1.5 h-3 w-1/2" />
          <Skeleton className="h-2 w-3/4" />
        </li>
        <li className="px-2 pt-2">
          <Skeleton className="mb-1.5 h-3 w-2/3" />
          <Skeleton className="h-2 w-1/2" />
        </li>
      </ul>
      <div className="border-t p-2 text-[10px] text-muted-foreground">
        Persistent history lands once the backend ships{" "}
        <code className="font-mono">/agent/conversations</code>.
      </div>
    </aside>
  );
}
