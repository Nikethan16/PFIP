"use client";

import * as React from "react";
import { ArrowUp, Loader2, Trash2, XCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Markdown } from "@/components/shared/markdown";
import { SuggestedStarters } from "@/components/chat/suggested-starters";
import { useAgentChat } from "@/lib/sse";
import { useAuthToken } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Full chat surface: scrolling message list + input. SSE streaming handled
 * inside `useAgentChat`. This is the only place we talk to `/agent/chat`.
 *
 * Keyboard:
 *   Enter       → send
 *   Shift+Enter → newline
 *   Esc         → cancel streaming
 *
 * Session persistence: messages survive reloads via `localStorage` inside
 * `useAgentChat`.
 */
export function MessageStream() {
  const token = useAuthToken();
  const endpoint = `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1"}/agent/chat`;
  const { messages, streaming, send, cancel, reset, error } = useAgentChat({
    token,
    endpoint,
  });

  const [draft, setDraft] = React.useState("");
  const scrollerRef = React.useRef<HTMLDivElement>(null);
  const inputRef = React.useRef<HTMLTextAreaElement>(null);

  React.useEffect(() => {
    scrollerRef.current?.scrollTo({
      top: scrollerRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

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

  // Global Esc handler to cancel a stream.
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && streaming) {
        cancel();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [cancel, streaming]);

  return (
    <div className="flex h-full flex-col">
      <div
        ref={scrollerRef}
        className="flex-1 space-y-4 overflow-y-auto px-1 py-4"
        role="log"
        aria-live="polite"
        aria-relevant="additions"
      >
        {messages.length === 0 ? (
          <div className="mx-auto max-w-md space-y-4 rounded-lg border border-dashed p-6 text-sm">
            <div className="text-center text-muted-foreground">
              Ask about a position, a regime call, or request a what-if. The
              agent can see your portfolio, the knowledge base, and live news.
              {/* TODO(user): seed this empty state with your favourite prompts */}
            </div>
            <SuggestedStarters onPick={(s) => onSend(s)} />
          </div>
        ) : null}

        {messages.map((m) => (
          <div
            key={m.id}
            className={cn(
              "flex gap-3",
              m.role === "user" ? "justify-end" : "justify-start",
            )}
          >
            <div
              className={cn(
                "max-w-[90%] rounded-lg px-4 py-2 text-sm leading-relaxed sm:max-w-[75%]",
                m.role === "user"
                  ? "bg-primary text-primary-foreground"
                  : "border bg-card",
              )}
            >
              {m.role === "assistant" ? (
                m.content ? (
                  <Markdown>{m.content}</Markdown>
                ) : null
              ) : (
                <div className="whitespace-pre-wrap">{m.content}</div>
              )}

              {m.pending ? (
                <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  <span>
                    {m.content ? "typing…" : "Thinking…"}
                  </span>
                </div>
              ) : null}

              {m.sources.length ? (
                <div className="mt-2 border-t pt-2">
                  <div className="mb-1 text-[10px] uppercase tracking-wider text-muted-foreground">
                    Sources
                  </div>
                  <ol className="flex flex-wrap gap-1 text-[11px]">
                    {m.sources.map((s, i) => (
                      <li
                        key={`${s.id}-${i}`}
                        className="inline-flex items-center gap-1 rounded border bg-background px-1.5 py-0.5 text-muted-foreground"
                        title={`${s.type} · ${s.id}`}
                      >
                        <span className="font-mono text-[10px]">
                          [{i + 1}]
                        </span>
                        <span className="font-medium">{s.type}</span>
                        <span className="truncate max-w-[12rem]">
                          {s.title}
                        </span>
                      </li>
                    ))}
                  </ol>
                </div>
              ) : null}
            </div>
          </div>
        ))}

        {error ? (
          <div className="mx-auto max-w-md rounded-md border border-destructive/50 bg-destructive/10 p-3 text-xs text-destructive">
            {error}
          </div>
        ) : null}
      </div>

      <div className="sticky bottom-0 border-t bg-background pt-3">
        <div className="flex items-end gap-2">
          <Textarea
            ref={inputRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Ask PFIP anything about markets, your positions, or tax…"
            rows={2}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                onSend();
              }
            }}
            className="min-h-[52px] resize-none"
            aria-label="Chat input"
          />
          {streaming ? (
            <Button
              onClick={cancel}
              variant="outline"
              size="icon"
              className="h-11 w-11 shrink-0"
              aria-label="Cancel"
              title="Cancel (Esc)"
            >
              <XCircle className="h-4 w-4" />
            </Button>
          ) : (
            <Button
              onClick={() => onSend()}
              disabled={!draft.trim()}
              size="icon"
              className="h-11 w-11 shrink-0"
              aria-label="Send"
            >
              <ArrowUp className="h-4 w-4" />
            </Button>
          )}
        </div>
        <div className="mt-1 flex items-center justify-between text-[11px] text-muted-foreground">
          <span>
            Enter sends · Shift+Enter newline · Esc cancels. PFIP can be wrong —
            cross-check before acting.
          </span>
          {messages.length ? (
            <button
              type="button"
              className="inline-flex items-center gap-1 hover:text-foreground"
              onClick={reset}
              title="Clear session"
            >
              <Trash2 className="h-3 w-3" /> Clear
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
