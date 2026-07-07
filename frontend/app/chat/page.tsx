"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";
import { MessageSquare, Plus, Sparkles, Trash2, Users, Wrench } from "lucide-react";

import { MessageStream } from "@/components/agent/message-stream";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { PageHeader } from "@/components/shared/page-header";
import { useConversations } from "@/lib/sse";
import { usePerspectives, useAgentTools, useOrchestrate } from "@/lib/api";
import { cn, formatIST } from "@/lib/utils";

/**
 * Chat page — the primary assistant surface, plus a "Perspectives" mode that
 * folds in the old three-lens panel (value / macro / risk) as a mode rather
 * than a separate nav page (C4). Deep-linkable via `?mode=panel`.
 *
 * Conversation history is client-side (localStorage via `useConversations`).
 */
type Mode = "chat" | "panel" | "tools";

export default function ChatPage() {
  return (
    <React.Suspense fallback={null}>
      <ChatPageInner />
    </React.Suspense>
  );
}

function ChatPageInner() {
  const { conversations, newChat, load, remove } = useConversations();
  const params = useSearchParams();
  const initialMode = params?.get("mode");
  const [mode, setMode] = React.useState<Mode>(
    initialMode === "panel" ? "panel" : initialMode === "tools" ? "tools" : "chat",
  );

  return (
    <div className="flex h-[calc(100dvh-9rem)] flex-col md:h-[calc(100dvh-7rem)]">
      <PageHeader
        title={mode === "chat" ? "Chat" : mode === "panel" ? "Perspectives" : "Tools"}
        description={
          mode === "chat"
            ? "Ask PFIP anything. Responses cite the portfolio, knowledge base, and live news."
            : mode === "panel"
              ? "One question, three independent expert lenses — value, macro, and risk. Advisory only."
              : "Type a request and the orchestrator routes it to a typed tool — e.g. “explain bitcoin”, “show my holdings”, “my calendar”."
        }
        flat
        actions={
          <div className="flex items-center gap-2">
            <ModeToggle mode={mode} onChange={setMode} />
            {mode === "chat" ? (
              <Button variant="outline" size="sm" className="gap-1" onClick={newChat}>
                <Plus className="h-3.5 w-3.5" />
                New chat
              </Button>
            ) : null}
          </div>
        }
      />

      {mode === "chat" ? (
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
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto rounded-xl border bg-card p-5">
          {mode === "panel" ? <PerspectivesPanel /> : <ToolsPanel />}
        </div>
      )}
    </div>
  );
}

function ModeToggle({ mode, onChange }: { mode: Mode; onChange: (m: Mode) => void }) {
  return (
    <div
      className="flex items-center gap-1 border border-border bg-secondary/40 p-1"
      role="tablist"
      aria-label="Chat mode"
    >
      {(
        [
          { id: "chat" as Mode, label: "Chat", icon: MessageSquare },
          { id: "panel" as Mode, label: "Perspectives", icon: Users },
          { id: "tools" as Mode, label: "Tools", icon: Wrench },
        ]
      ).map(({ id, label, icon: Icon }) => (
        <button
          key={id}
          type="button"
          role="tab"
          aria-selected={mode === id}
          onClick={() => onChange(id)}
          className={cn(
            "inline-flex items-center gap-1.5 px-3 py-1.5 font-label text-xs uppercase tracking-wider transition-colors",
            mode === id ? "bg-card text-primary shadow-sm" : "text-muted-foreground hover:text-foreground",
          )}
        >
          <Icon className="h-3.5 w-3.5" />
          {label}
        </button>
      ))}
    </div>
  );
}

const PERSONA_LABEL: Record<string, string> = {
  value: "Value investor",
  macro: "Macro strategist",
  risk: "Risk manager",
};

function PerspectivesPanel() {
  const [q, setQ] = React.useState("");
  const ask = usePerspectives();

  const onAsk = (e: React.FormEvent) => {
    e.preventDefault();
    if (q.trim()) ask.mutate({ question: q.trim() });
  };

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <form onSubmit={onAsk} className="space-y-3">
        <Textarea
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="e.g. Is now a good time to add to Indian IT, or wait?"
          rows={3}
          aria-label="Question"
        />
        <Button type="submit" disabled={ask.isPending || !q.trim()}>
          {ask.isPending ? "Consulting the panel…" : "Ask the panel"}
        </Button>
      </form>

      {ask.isError ? (
        <div className="border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          {(ask.error as Error).message}
        </div>
      ) : ask.data ? (
        <div className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-3">
            {ask.data.perspectives.map((p) => (
              <div key={p.persona} className="border border-border/60 bg-background p-4">
                <div className="eyebrow mb-2">{PERSONA_LABEL[p.persona] ?? p.persona}</div>
                <p className="text-sm leading-relaxed">{p.view}</p>
              </div>
            ))}
          </div>
          <p className="text-[11px] text-muted-foreground">{ask.data.disclaimer}</p>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">
          Ask a question above to get three independent expert takes.
        </p>
      )}
    </div>
  );
}

const TOOL_EXAMPLES = [
  "explain bitcoin",
  "show my holdings",
  "what's on my calendar",
  "research TCS.NS",
  "tax summary for 2024-25",
  "how's my p&l",
];

function ToolsPanel() {
  const [q, setQ] = React.useState("");
  const orchestrate = useOrchestrate();
  const { data: tools } = useAgentTools();

  const run = (message: string) => {
    if (message.trim()) orchestrate.mutate({ message: message.trim() });
  };

  const res = orchestrate.data;

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          run(q);
        }}
        className="flex flex-wrap items-center gap-2"
      >
        <Input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="e.g. explain bitcoin"
          className="min-w-[14rem] flex-1"
        />
        <Button type="submit" disabled={orchestrate.isPending || !q.trim()}>
          {orchestrate.isPending ? "Routing…" : "Run"}
        </Button>
      </form>

      <div className="flex flex-wrap gap-1.5">
        {TOOL_EXAMPLES.map((ex) => (
          <button
            key={ex}
            type="button"
            onClick={() => {
              setQ(ex);
              run(ex);
            }}
            className="border border-border/60 bg-secondary/40 px-2.5 py-1 text-xs transition-colors hover:border-primary/50 hover:text-primary"
          >
            {ex}
          </button>
        ))}
      </div>

      {orchestrate.isError ? (
        <div className="border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          {(orchestrate.error as Error).message}
        </div>
      ) : res ? (
        res.matched ? (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-sm">
              <span className="eyebrow">Tool</span>
              <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-primary">
                {res.tool}
              </code>
              {Object.keys(res.args ?? {}).length ? (
                <span className="font-mono text-xs text-muted-foreground">
                  {JSON.stringify(res.args)}
                </span>
              ) : null}
            </div>
            <pre className="max-h-[420px] overflow-auto border border-border/60 bg-secondary/20 p-3 text-xs leading-relaxed">
              {JSON.stringify(res.result, null, 2)}
            </pre>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            {res.note ?? "No tool matched — try the Chat tab for open-ended questions."}
          </p>
        )
      ) : (
        <p className="text-sm text-muted-foreground">
          {tools?.length
            ? `${tools.length} tools available. Type a request or pick an example.`
            : "Type a request or pick an example above."}
        </p>
      )}
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
