"use client";

import * as React from "react";
import {
  ArrowUp,
  Bot,
  ExternalLink,
  Loader2,
  Sparkles,
  Square,
  Trash2,
  User as UserIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Markdown } from "@/components/shared/markdown";
import { SuggestedStarters } from "@/components/chat/suggested-starters";
import { useAgentChat } from "@/lib/sse";
import { AGENT_CHAT_ENDPOINT, useAuthToken } from "@/lib/api";
import { cn } from "@/lib/utils";
import { toast } from "@/components/ui/toast";
import type { SSESourceTag } from "@/lib/sse";

/**
 * Full chat surface. Visually inspired by Claude / ChatGPT:
 *   - Wide reading column centered on the page.
 *   - User bubbles on the right with soft primary tint, assistant messages
 *     flow on the left without a bubble for a less "boxy" feel.
 *   - Sources rendered as inline footnote chips with hover preview.
 *   - Sticky composer at the bottom with auto-expanding textarea.
 *
 * Keyboard
 *   Enter         → send (Cmd/Ctrl+Enter also works)
 *   Shift+Enter   → newline
 *   Esc           → cancel streaming
 */
export function MessageStream() {
  const token = useAuthToken();
  const { messages, streaming, send, cancel, reset, error } = useAgentChat({
    token,
    endpoint: AGENT_CHAT_ENDPOINT,
  });

  const [draft, setDraft] = React.useState("");
  const scrollerRef = React.useRef<HTMLDivElement>(null);
  const inputRef = React.useRef<HTMLTextAreaElement>(null);

  // Auto-scroll on new messages — but only when the user is near the bottom
  // already, so they aren't yanked away while reading scroll-back history.
  React.useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    const nearBottom =
      el.scrollHeight - el.scrollTop - el.clientHeight < 200;
    if (nearBottom) {
      el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    }
  }, [messages]);

  // Auto-grow textarea up to ~6 lines.
  React.useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [draft]);

  const onSend = React.useCallback(
    (text?: string) => {
      const payload = (text ?? draft).trim();
      if (!payload || streaming) return;
      send(payload);
      setDraft("");
      inputRef.current?.focus();
    },
    [draft, send, streaming],
  );

  // Toast error if SSE fails entirely.
  React.useEffect(() => {
    if (error) toast.error(`Chat error — ${error}`);
  }, [error]);

  // Global Esc handler to cancel a stream.
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && streaming) cancel();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [cancel, streaming]);

  return (
    <div className="flex h-full flex-col">
      {/* Scrolling messages */}
      <div
        ref={scrollerRef}
        className="flex-1 overflow-y-auto px-1 py-4"
        role="log"
        aria-live="polite"
        aria-relevant="additions"
      >
        <div className="mx-auto w-full max-w-3xl space-y-6">
          {messages.length === 0 ? (
            <EmptyChat onPick={onSend} />
          ) : (
            messages.map((m) =>
              m.role === "user" ? (
                <UserBubble key={m.id} content={m.content} />
              ) : (
                <AssistantTurn
                  key={m.id}
                  content={m.content}
                  pending={!!m.pending}
                  sources={m.sources}
                />
              ),
            )
          )}
        </div>
      </div>

      {/* Composer */}
      <div className="border-t bg-background pt-3">
        <div className="mx-auto w-full max-w-3xl">
          <div className="flex items-end gap-2 rounded-xl border bg-card p-2 shadow-sm focus-within:ring-2 focus-within:ring-ring/40">
            <Textarea
              ref={inputRef}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Ask PFIP anything about markets, your positions, or tax…"
              rows={1}
              onKeyDown={(e) => {
                if (
                  e.key === "Enter" &&
                  !e.shiftKey &&
                  !(e.metaKey || e.ctrlKey)
                ) {
                  e.preventDefault();
                  onSend();
                } else if (
                  e.key === "Enter" &&
                  (e.metaKey || e.ctrlKey)
                ) {
                  e.preventDefault();
                  onSend();
                }
              }}
              className="min-h-[28px] flex-1 resize-none border-0 bg-transparent p-1.5 text-sm shadow-none focus-visible:ring-0"
              aria-label="Chat input"
            />
            {streaming ? (
              <Button
                onClick={cancel}
                variant="outline"
                size="icon"
                className="h-9 w-9 shrink-0"
                aria-label="Stop generating"
                title="Stop (Esc)"
              >
                <Square className="h-3.5 w-3.5" />
              </Button>
            ) : (
              <Button
                onClick={() => onSend()}
                disabled={!draft.trim()}
                size="icon"
                className="h-9 w-9 shrink-0"
                aria-label="Send"
                title="Send (Enter)"
              >
                <ArrowUp className="h-4 w-4" />
              </Button>
            )}
          </div>
          <div className="mt-1.5 flex items-center justify-between text-[11px] text-muted-foreground">
            <span>
              Enter sends · Shift+Enter newline · Esc cancels · PFIP can be
              wrong — cross-check before acting.
            </span>
            {messages.length ? (
              <button
                type="button"
                className="inline-flex items-center gap-1 hover:text-foreground"
                onClick={() => {
                  reset();
                  toast.success("Conversation cleared");
                }}
                title="Clear conversation"
              >
                <Trash2 className="h-3 w-3" /> Clear
              </button>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

function EmptyChat({ onPick }: { onPick: (s: string) => void }) {
  return (
    <div className="mx-auto max-w-xl space-y-6 py-12 text-center">
      <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary">
        <Sparkles className="h-5 w-5" />
      </div>
      <div className="space-y-1">
        <h2 className="text-lg font-semibold tracking-tight">
          How can PFIP help you today?
        </h2>
        <p className="text-sm text-muted-foreground">
          The agent sees your portfolio, the knowledge base, and live news. Try
          one of these or write your own.
        </p>
      </div>
      <SuggestedStarters onPick={onPick} className="items-center" />
    </div>
  );
}

function UserBubble({ content }: { content: string }) {
  return (
    <div className="flex items-start justify-end gap-2">
      <div className="max-w-[80%] rounded-2xl rounded-br-md bg-primary/10 px-4 py-2.5 text-sm leading-relaxed text-foreground">
        <div className="whitespace-pre-wrap">{content}</div>
      </div>
      <Avatar fallback={<UserIcon className="h-3.5 w-3.5" />} />
    </div>
  );
}

function AssistantTurn({
  content,
  pending,
  sources,
}: {
  content: string;
  pending: boolean;
  sources: SSESourceTag[];
}) {
  return (
    <div className="flex items-start gap-2.5">
      <Avatar
        fallback={<Bot className="h-3.5 w-3.5" />}
        tone="primary"
      />
      <div className="min-w-0 flex-1 space-y-2">
        <div className="prose prose-sm dark:prose-invert max-w-none text-sm leading-relaxed">
          {content ? (
            <Markdown>{content}</Markdown>
          ) : pending ? (
            <span className="pfip-shimmer font-medium">Thinking…</span>
          ) : (
            <span className="text-muted-foreground">No response.</span>
          )}
        </div>

        {pending && content ? (
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" />
            <span>typing</span>
          </div>
        ) : null}

        {sources.length ? <SourceList sources={sources} /> : null}
      </div>
    </div>
  );
}

function SourceList({ sources }: { sources: SSESourceTag[] }) {
  return (
    <div className="border-t pt-2">
      <div className="mb-1 text-[10px] uppercase tracking-wider text-muted-foreground">
        Sources
      </div>
      <ol className="flex flex-wrap gap-1 text-[11px]">
        {sources.map((s, i) => (
          <li key={`${s.id}-${i}`}>
            <SourceChip index={i + 1} source={s} />
          </li>
        ))}
      </ol>
    </div>
  );
}

function SourceChip({
  index,
  source,
}: {
  index: number;
  source: SSESourceTag;
}) {
  const typeColor =
    source.type === "news"
      ? "bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-500/30"
      : source.type === "kb"
        ? "bg-indigo-500/10 text-indigo-700 dark:text-indigo-300 border-indigo-500/30"
        : "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/30";
  return (
    <span
      className={cn(
        "group relative inline-flex items-center gap-1 rounded border px-1.5 py-0.5 transition-colors hover:bg-accent",
        typeColor,
      )}
      title={`${source.type.toUpperCase()} · ${source.id}\n${source.title}`}
    >
      <span className="font-mono text-[10px]">[{index}]</span>
      <span className="font-medium uppercase">{source.type}</span>
      <span className="hidden max-w-[14rem] truncate sm:inline">
        {source.title}
      </span>
      <ExternalLink className="h-2.5 w-2.5 opacity-50" />
    </span>
  );
}

function Avatar({
  fallback,
  tone,
}: {
  fallback: React.ReactNode;
  tone?: "primary" | "neutral";
}) {
  return (
    <div
      className={cn(
        "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border text-xs",
        tone === "primary"
          ? "border-primary/40 bg-primary/10 text-primary"
          : "border-border bg-muted text-muted-foreground",
      )}
    >
      {fallback}
    </div>
  );
}
