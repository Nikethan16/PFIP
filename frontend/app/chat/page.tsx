"use client";

import * as React from "react";
import { MessageSquare, Plus, Sparkles, Trash2 } from "lucide-react";

import { MessageStream } from "@/components/agent/message-stream";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/shared/page-header";
import { useConversations } from "@/lib/sse";
import { cn, formatIST } from "@/lib/utils";

/**
 * Chat page. We give chat its own full-bleed surface (no inner card border)
 * so it feels like a dedicated workspace rather than a widget on a page.
 *
 * Conversation history is fully client-side: the active thread lives in
 * localStorage (managed by `useAgentChat`), and prior threads are archived
 * locally via `useConversations`. There is no backend persistence endpoint
 * yet, so the sidebar is honest about where this data lives.
 */
export default function ChatPage() {
  const { conversations, newChat, load, remove } = useConversations();

  return (
    <div className="flex h-[calc(100dvh-9rem)] flex-col md:h-[calc(100dvh-7rem)]">
      <PageHeader
        title="Chat"
        description="Ask PFIP anything. Responses cite the portfolio, knowledge base, and live news."
        flat
        actions={
          <Button
            variant="outline"
            size="sm"
            className="gap-1"
            onClick={newChat}
          >
            <Plus className="h-3.5 w-3.5" />
            New chat
          </Button>
        }
      />

      <div className="flex min-h-0 flex-1 gap-3">
        <ConversationSidebar
          conversations={conversations}
          onNewChat={newChat}
          onLoad={load}
          onRemove={remove}
        />
        <div className="flex min-w-0 flex-1 flex-col rounded-xl border bg-card">
          <MessageStream />
        </div>
      </div>
    </div>
  );
}

function ConversationSidebar({
  conversations,
  onNewChat,
  onLoad,
  onRemove,
}: {
  conversations: ReturnType<typeof useConversations>["conversations"];
  onNewChat: () => void;
  onLoad: (id: string) => void;
  onRemove: (id: string) => void;
}) {
  return (
    <aside className="hidden w-64 shrink-0 flex-col rounded-xl border bg-card md:flex">
      <div className="flex items-center justify-between border-b px-3 py-2.5">
        <div className="flex items-center gap-2 text-xs font-medium">
          <MessageSquare className="h-3.5 w-3.5 text-muted-foreground" />
          Conversations
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          onClick={onNewChat}
          aria-label="New chat"
          title="New chat"
        >
          <Plus className="h-3.5 w-3.5" />
        </Button>
      </div>

      <ul className="flex-1 space-y-px overflow-y-auto p-2">
        {/* The live thread always sits at the top. */}
        <li>
          <div className="block w-full rounded-md bg-accent px-2 py-2 text-left text-accent-foreground">
            <div className="flex items-center gap-1.5 text-xs font-medium">
              <Sparkles className="h-3 w-3 text-primary" />
              <span className="truncate">Current session</span>
            </div>
            <div className="mt-0.5 truncate text-[11px] text-muted-foreground">
              Live conversation (stored locally).
            </div>
          </div>
        </li>

        {conversations.length === 0 ? (
          <li className="px-2 pt-4 text-center text-[11px] text-muted-foreground">
            No saved conversations yet. Start a new chat to archive this one.
          </li>
        ) : (
          conversations.map((c) => (
            <li key={c.id} className="group relative">
              <button
                type="button"
                onClick={() => onLoad(c.id)}
                className={cn(
                  "block w-full rounded-md px-2 py-2 pr-7 text-left transition-colors",
                  "hover:bg-accent/60",
                )}
                title={`Open · ${c.messageCount} messages`}
              >
                <div className="flex items-center gap-1.5 text-xs font-medium">
                  <MessageSquare className="h-3 w-3 text-muted-foreground" />
                  <span className="truncate">{c.title}</span>
                </div>
                <div className="mt-0.5 truncate text-[11px] text-muted-foreground">
                  {formatIST(c.savedAt, "dd MMM HH:mm")} · {c.messageCount} msg
                </div>
              </button>
              <button
                type="button"
                onClick={() => onRemove(c.id)}
                className="absolute right-1.5 top-1.5 rounded p-1 text-muted-foreground opacity-0 transition-opacity hover:text-destructive focus-visible:opacity-100 group-hover:opacity-100"
                aria-label={`Delete conversation: ${c.title}`}
                title="Delete"
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </li>
          ))
        )}
      </ul>

      <div className="border-t p-2 text-[10px] text-muted-foreground">
        Conversations are stored locally in this browser only.
      </div>
    </aside>
  );
}
