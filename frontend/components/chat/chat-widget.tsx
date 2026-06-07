"use client";

import * as React from "react";
import Link from "next/link";
import {
  ArrowUp,
  Bot,
  Loader2,
  MessageSquare,
  Sparkles,
  Square,
  User as UserIcon,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Markdown } from "@/components/shared/markdown";
import { useAgentChat } from "@/lib/sse";
import { useAuthToken } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { ChatTurn } from "@/lib/sse";

/**
 * Window event the global ChatWidget listens for so ANY surface can pop the
 * agent open (optionally with a message prefilled). Reuses the same loosely-
 * coupled window-event pattern as `useAgentChat`'s ACTIVE_CHANGED_EVENT — no
 * prop drilling or shared store needed. The detail carries an optional
 * `prefill`; when present the panel auto-sends it once on open.
 */
export const OPEN_AGENT_CHAT_EVENT = "pfip:chat:open";

export interface OpenAgentChatDetail {
  /** If set, the panel sends this message automatically when it opens. */
  prefill?: string;
}

/**
 * Imperatively open the floating agent chat from anywhere (e.g. an
 * "Ask the agent for a full report" button). Optionally prefill + send a
 * message. No-op during SSR.
 */
export function openAgentChat(prefill?: string): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent<OpenAgentChatDetail>(OPEN_AGENT_CHAT_EVENT, {
      detail: prefill ? { prefill } : {},
    }),
  );
}

/**
 * Floating "Ask the agent" widget mounted app-wide (except /login, gated by
 * AppShell). It deliberately reuses the *same* `useAgentChat` hook + endpoint as
 * the full `/chat` page, which means it talks to the same agent over the same
 * authenticated SSE stream AND shares the same localStorage-backed active
 * conversation. Opening the widget, sending a turn, then visiting /chat shows
 * the same thread — and the hook's ACTIVE_CHANGED_EVENT keeps both surfaces in
 * sync when the user starts a new chat from either place.
 *
 * Accessibility:
 *   - FAB has an aria-label and clears the mobile bottom-nav.
 *   - Panel is a labelled dialog; Esc and click-outside close it; the input is
 *     focused on open and focus returns to the FAB on close. A lightweight
 *     focus trap keeps Tab within the panel.
 */
export function ChatWidget() {
  const [open, setOpen] = React.useState(false);
  // A pending prefill captured from an `openAgentChat(...)` call; handed to the
  // panel which sends it once on mount, then clears it.
  const [prefill, setPrefill] = React.useState<string | undefined>(undefined);
  const fabRef = React.useRef<HTMLButtonElement>(null);

  const close = React.useCallback(() => {
    setOpen(false);
    setPrefill(undefined);
    // Return focus to the trigger for keyboard users.
    fabRef.current?.focus();
  }, []);

  // Listen for imperative open requests from anywhere in the app.
  React.useEffect(() => {
    if (typeof window === "undefined") return;
    const onOpen = (e: Event) => {
      const detail = (e as CustomEvent<OpenAgentChatDetail>).detail;
      setPrefill(detail?.prefill);
      setOpen(true);
    };
    window.addEventListener(OPEN_AGENT_CHAT_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_AGENT_CHAT_EVENT, onOpen);
  }, []);

  return (
    <>
      {!open ? (
        <button
          ref={fabRef}
          type="button"
          onClick={() => setOpen(true)}
          aria-label="Ask the agent"
          title="Ask the agent"
          className={cn(
            "fixed bottom-[4.75rem] right-4 z-50 flex h-14 w-14 items-center justify-center rounded-full",
            "bg-primary text-primary-foreground shadow-lg shadow-primary/30",
            "ring-offset-background transition-all hover:scale-105 hover:bg-primary/90",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
            "md:bottom-6 md:right-6",
          )}
        >
          <Sparkles className="h-6 w-6" />
        </button>
      ) : null}

      {open ? <ChatPanel onClose={close} prefill={prefill} /> : null}
    </>
  );
}

function ChatPanel({
  onClose,
  prefill,
}: {
  onClose: () => void;
  prefill?: string;
}) {
  const token = useAuthToken();
  const endpoint = `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1"}/agent/chat`;
  const { messages, streaming, send, cancel, error } = useAgentChat({
    token,
    endpoint,
  });

  const [draft, setDraft] = React.useState("");
  const panelRef = React.useRef<HTMLDivElement>(null);
  const scrollerRef = React.useRef<HTMLDivElement>(null);
  const inputRef = React.useRef<HTMLTextAreaElement>(null);

  // Focus the input when the panel opens.
  React.useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // If opened with a prefill (e.g. from the Diligence "Ask the agent" button),
  // send it exactly once. Guarded by a ref so re-renders / token changes don't
  // resend. We send straight through rather than seeding the draft so the user
  // gets an immediate answer.
  const prefillSentRef = React.useRef(false);
  React.useEffect(() => {
    if (!prefill || prefillSentRef.current) return;
    prefillSentRef.current = true;
    send(prefill);
  }, [prefill, send]);

  // Esc closes, click-outside closes, and Tab is trapped within the panel.
  React.useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        // If we're mid-stream, first Esc stops generation (mirrors /chat);
        // otherwise it closes the panel.
        if (streaming) {
          cancel();
        } else {
          onClose();
        }
        return;
      }
      if (e.key === "Tab" && panelRef.current) {
        const focusables = panelRef.current.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])',
        );
        if (focusables.length === 0) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (!first || !last) return;
        const active = document.activeElement;
        if (e.shiftKey && active === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && active === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    const onPointerDown = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("mousedown", onPointerDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("mousedown", onPointerDown);
    };
  }, [cancel, onClose, streaming]);

  // Keep the latest turn in view as tokens stream in.
  React.useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const onSend = React.useCallback(() => {
    const payload = draft.trim();
    if (!payload || streaming) return;
    send(payload);
    setDraft("");
    inputRef.current?.focus();
  }, [draft, send, streaming]);

  return (
    <div
      ref={panelRef}
      role="dialog"
      aria-modal="true"
      aria-label="Ask the agent"
      className={cn(
        "fixed z-50 flex flex-col overflow-hidden border bg-card text-card-foreground shadow-2xl",
        // Mobile: near-fullscreen sheet clearing the bottom nav.
        "inset-x-2 bottom-2 top-2 rounded-xl",
        // Desktop: bottom-right drawer card.
        "sm:inset-auto sm:bottom-6 sm:right-6 sm:top-auto sm:h-[70vh] sm:w-[380px] sm:max-w-[calc(100vw-3rem)]",
      )}
    >
      {/* Header */}
      <header className="flex shrink-0 items-center justify-between gap-2 border-b px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-full border border-primary/40 bg-primary/10 text-primary">
            <Sparkles className="h-3.5 w-3.5" />
          </span>
          <h2 className="display-serif text-base font-semibold">
            Ask the agent
          </h2>
        </div>
        <div className="flex items-center gap-1">
          <Link
            href={"/chat" as never}
            onClick={onClose}
            className="hidden items-center gap-1 rounded-md px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground sm:inline-flex"
          >
            <MessageSquare className="h-3 w-3" />
            Open full chat →
          </Link>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={onClose}
            aria-label="Close chat"
            title="Close (Esc)"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      </header>

      {/* Messages */}
      <div
        ref={scrollerRef}
        className="flex-1 overflow-y-auto px-3 py-3"
        role="log"
        aria-live="polite"
        aria-relevant="additions"
      >
        {messages.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="space-y-4">
            {messages.map((m) => (
              <WidgetTurn key={m.id} turn={m} />
            ))}
          </div>
        )}
        {error ? (
          <p className="mt-3 rounded-md border border-destructive/40 bg-destructive/10 px-2.5 py-1.5 text-[11px] text-destructive">
            {error}
          </p>
        ) : null}
      </div>

      {/* Composer */}
      <div className="shrink-0 border-t bg-background p-2.5">
        <div className="flex items-end gap-2 rounded-lg border bg-card p-1.5 focus-within:ring-2 focus-within:ring-ring/40">
          <Textarea
            ref={inputRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Ask about markets, positions, or tax…"
            rows={1}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                onSend();
              }
            }}
            className="max-h-28 min-h-[28px] flex-1 resize-none border-0 bg-transparent p-1.5 text-sm shadow-none focus-visible:ring-0"
            aria-label="Chat input"
          />
          {streaming ? (
            <Button
              type="button"
              onClick={cancel}
              variant="outline"
              size="icon"
              className="h-8 w-8 shrink-0"
              aria-label="Stop generating"
              title="Stop (Esc)"
            >
              <Square className="h-3.5 w-3.5" />
            </Button>
          ) : (
            <Button
              type="button"
              onClick={onSend}
              disabled={!draft.trim()}
              size="icon"
              className="h-8 w-8 shrink-0"
              aria-label="Send"
              title="Send (Enter)"
            >
              <ArrowUp className="h-4 w-4" />
            </Button>
          )}
        </div>
        <p className="mt-1.5 px-0.5 text-[10px] text-muted-foreground">
          Enter sends · Shift+Enter newline · shares your{" "}
          <Link
            href={"/chat" as never}
            onClick={onClose}
            className="underline hover:text-foreground"
          >
            chat
          </Link>{" "}
          history.
        </p>
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 px-4 text-center">
      <span className="flex h-10 w-10 items-center justify-center rounded-full bg-primary/10 text-primary">
        <Sparkles className="h-5 w-5" />
      </span>
      <p className="text-sm font-medium">How can PFIP help?</p>
      <p className="text-[11px] leading-relaxed text-muted-foreground">
        The agent sees your portfolio, the knowledge base, and live news. Ask a
        quick question without leaving this page.
      </p>
    </div>
  );
}

function WidgetTurn({ turn }: { turn: ChatTurn }) {
  if (turn.role === "user") {
    return (
      <div className="flex items-start justify-end gap-2">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-primary/10 px-3 py-2 text-sm leading-relaxed text-foreground">
          <div className="whitespace-pre-wrap">{turn.content}</div>
        </div>
        <Avatar tone="neutral">
          <UserIcon className="h-3 w-3" />
        </Avatar>
      </div>
    );
  }
  return (
    <div className="flex items-start gap-2">
      <Avatar tone="primary">
        <Bot className="h-3 w-3" />
      </Avatar>
      <div className="min-w-0 flex-1 text-sm leading-relaxed">
        {turn.content ? (
          <Markdown>{turn.content}</Markdown>
        ) : turn.pending ? (
          <span className="pfip-shimmer font-medium text-muted-foreground">
            Thinking…
          </span>
        ) : (
          <span className="text-muted-foreground">No response.</span>
        )}
        {turn.pending && turn.content ? (
          <div className="mt-1 flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" />
            <span>typing</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function Avatar({
  tone,
  children,
}: {
  tone: "primary" | "neutral";
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-xs",
        tone === "primary"
          ? "border-primary/40 bg-primary/10 text-primary"
          : "border-border bg-muted text-muted-foreground",
      )}
    >
      {children}
    </div>
  );
}
