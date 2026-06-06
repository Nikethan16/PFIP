"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const STORAGE_KEY = "pfip:chat:messages:v1";
/** Index of locally-archived prior conversations (newest first). */
const INDEX_KEY = "pfip:chat:index:v1";
/** Per-conversation message store, keyed by `${CONV_PREFIX}${id}`. */
const CONV_PREFIX = "pfip:chat:conv:";
/**
 * Fired on `window` whenever the active conversation is swapped out from
 * underneath a mounted `useAgentChat` (e.g. "New chat" or switching threads).
 * The hook listens for it and re-hydrates from localStorage so the open
 * message stream reflects the change without a full reload.
 */
const ACTIVE_CHANGED_EVENT = "pfip:chat:active-changed";

/** A locally-stored prior conversation, surfaced in the sidebar. */
export interface ConversationMeta {
  id: string;
  title: string;
  /** ISO-8601 timestamp the conversation was archived. */
  savedAt: string;
  messageCount: number;
}

function readMessages(key: string): ChatTurn[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as ChatTurn[];
    return parsed.map((m) => ({ ...m, pending: false }));
  } catch {
    return [];
  }
}

function readIndex(): ConversationMeta[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(INDEX_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (m): m is ConversationMeta =>
        typeof m === "object" &&
        m !== null &&
        typeof (m as ConversationMeta).id === "string",
    );
  } catch {
    return [];
  }
}

function writeIndex(index: ConversationMeta[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(INDEX_KEY, JSON.stringify(index));
  } catch {
    // Storage quota / private mode — fine to ignore.
  }
}

/** Derive a short, human-readable title from the first user turn. */
function deriveTitle(messages: ChatTurn[]): string {
  const firstUser = messages.find((m) => m.role === "user");
  const text = firstUser?.content.trim() ?? "";
  if (!text) return "Untitled chat";
  return text.length > 48 ? `${text.slice(0, 48)}…` : text;
}

/**
 * Minimal client for backend SSE endpoints. Native `EventSource` cannot send
 * headers or POST bodies, so we use `fetch` + a streaming reader instead.
 *
 * Events accepted (see /docs/CONTRACTS.md §7):
 *   event: token   data: {"text": "..."}
 *   event: source  data: {type, id, title}
 *   event: signal  data: { ...Signal }
 *   event: done    data: {}
 */

export type SSESourceTag = {
  type: "kb" | "news" | "db";
  id: string;
  title: string;
};

export interface UseAgentChatResult {
  messages: ChatTurn[];
  streaming: boolean;
  error: string | null;
  send: (text: string) => void;
  reset: () => void;
  cancel: () => void;
}

export interface ChatTurn {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources: SSESourceTag[];
  pending?: boolean;
}

interface UseAgentChatArgs {
  token: string | null;
  /** Full URL, typically `${NEXT_PUBLIC_API_URL}/agent/chat`. */
  endpoint: string;
}

export function useAgentChat({
  token,
  endpoint,
}: UseAgentChatArgs): UseAgentChatResult {
  // Drop any message still flagged "pending" on load — those never completed.
  const [messages, setMessages] = useState<ChatTurn[]>(() =>
    readMessages(STORAGE_KEY),
  );
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  // Re-hydrate when the active conversation is swapped out from elsewhere
  // (New chat / switching threads via `useConversations`). We abort any
  // in-flight stream first so tokens don't bleed into the new thread.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const onActiveChanged = () => {
      controllerRef.current?.abort();
      setStreaming(false);
      setError(null);
      setMessages(readMessages(STORAGE_KEY));
    };
    window.addEventListener(ACTIVE_CHANGED_EVENT, onActiveChanged);
    return () =>
      window.removeEventListener(ACTIVE_CHANGED_EVENT, onActiveChanged);
  }, []);

  // Persist messages to localStorage whenever they change (throttled).
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      // Don't persist an in-flight pending assistant turn's transient state
      // every token — but since state updates batch, this is cheap enough.
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
    } catch {
      // Storage quota / private mode — fine to ignore.
    }
  }, [messages]);

  const reset = useCallback(() => {
    controllerRef.current?.abort();
    setMessages([]);
    setStreaming(false);
    setError(null);
    if (typeof window !== "undefined") {
      try {
        window.localStorage.removeItem(STORAGE_KEY);
      } catch {
        // ignore
      }
    }
  }, []);

  const cancel = useCallback(() => {
    controllerRef.current?.abort();
    setStreaming(false);
  }, []);

  useEffect(() => {
    return () => controllerRef.current?.abort();
  }, []);

  const send = useCallback(
    (text: string) => {
      if (!text.trim()) return;
      setError(null);

      const userTurn: ChatTurn = {
        id: crypto.randomUUID(),
        role: "user",
        content: text,
        sources: [],
      };
      const assistantTurn: ChatTurn = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: "",
        sources: [],
        pending: true,
      };
      setMessages((prev) => [...prev, userTurn, assistantTurn]);
      setStreaming(true);

      const controller = new AbortController();
      controllerRef.current = controller;

      void (async () => {
        try {
          const resp = await fetch(endpoint, {
            method: "POST",
            signal: controller.signal,
            headers: {
              "Content-Type": "application/json",
              Accept: "text/event-stream",
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
            body: JSON.stringify({ message: text }),
          });

          if (!resp.ok || !resp.body) {
            throw new Error(`HTTP ${resp.status}`);
          }

          const reader = resp.body.getReader();
          const decoder = new TextDecoder();
          let buffer = "";

          while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            // Each event is terminated by a blank line.
            const parts = buffer.split("\n\n");
            buffer = parts.pop() ?? "";

            for (const block of parts) {
              const ev = parseSSEBlock(block);
              if (!ev) continue;
              if (ev.event === "token") {
                setMessages((prev) =>
                  updateLastAssistant(prev, (turn) => ({
                    ...turn,
                    content: turn.content + (ev.data.text ?? ""),
                  })),
                );
              } else if (ev.event === "source") {
                const src = ev.data as SSESourceTag;
                setMessages((prev) =>
                  updateLastAssistant(prev, (turn) => ({
                    ...turn,
                    sources: [...turn.sources, src],
                  })),
                );
              } else if (ev.event === "done") {
                setMessages((prev) =>
                  updateLastAssistant(prev, (turn) => ({
                    ...turn,
                    pending: false,
                  })),
                );
              }
              // `signal` events are consumed elsewhere; we ignore them here.
            }
          }
        } catch (err) {
          if ((err as Error).name !== "AbortError") {
            setError((err as Error).message);
            setMessages((prev) =>
              updateLastAssistant(prev, (turn) => ({
                ...turn,
                pending: false,
                content:
                  turn.content ||
                  "Sorry — I ran into a problem reaching the agent.",
              })),
            );
          }
        } finally {
          setStreaming(false);
        }
      })();
    },
    [endpoint, token],
  );

  return { messages, streaming, error, send, reset, cancel };
}

export interface UseConversationsResult {
  /** Archived prior conversations, newest first. */
  conversations: ConversationMeta[];
  /**
   * Archive the current active thread (if it has any messages) under a new id,
   * then clear the active store so the user gets a blank canvas. No-op archive
   * when the current thread is empty.
   */
  newChat: () => void;
  /** Swap an archived conversation into the active store and open it. */
  load: (id: string) => void;
  /** Delete an archived conversation from local storage. */
  remove: (id: string) => void;
}

/**
 * Lightweight, fully client-side conversation history. There is no backend
 * persistence endpoint yet, so prior threads live in localStorage alongside the
 * active conversation that `useAgentChat` manages. Switching or starting a new
 * chat rewrites the active `STORAGE_KEY` and fires `ACTIVE_CHANGED_EVENT` so any
 * mounted `useAgentChat` re-hydrates in place.
 */
export function useConversations(): UseConversationsResult {
  const [conversations, setConversations] = useState<ConversationMeta[]>(() =>
    readIndex(),
  );

  // Keep the list fresh if storage is mutated in another tab.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const onStorage = (e: StorageEvent) => {
      if (e.key === INDEX_KEY) setConversations(readIndex());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const archiveActive = useCallback((): ConversationMeta[] => {
    const active = readMessages(STORAGE_KEY).filter((m) => m.content.trim());
    if (active.length === 0) return readIndex();
    const id = crypto.randomUUID();
    const meta: ConversationMeta = {
      id,
      title: deriveTitle(active),
      savedAt: new Date().toISOString(),
      messageCount: active.length,
    };
    try {
      window.localStorage.setItem(
        `${CONV_PREFIX}${id}`,
        JSON.stringify(active),
      );
    } catch {
      // Storage quota / private mode — skip archiving rather than throwing.
      return readIndex();
    }
    const next = [meta, ...readIndex()];
    writeIndex(next);
    return next;
  }, []);

  const newChat = useCallback(() => {
    if (typeof window === "undefined") return;
    const next = archiveActive();
    try {
      window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
    setConversations(next);
    window.dispatchEvent(new Event(ACTIVE_CHANGED_EVENT));
  }, [archiveActive]);

  const load = useCallback(
    (id: string) => {
      if (typeof window === "undefined") return;
      const raw = window.localStorage.getItem(`${CONV_PREFIX}${id}`);
      if (!raw) return;
      // Archive whatever's currently active before overwriting it, so the
      // user never silently loses the thread they were just in.
      const afterArchive = archiveActive();
      try {
        window.localStorage.setItem(STORAGE_KEY, raw);
        // The just-loaded thread is now active; drop it from the archive list
        // and its standalone store to avoid a duplicate entry.
        window.localStorage.removeItem(`${CONV_PREFIX}${id}`);
      } catch {
        // ignore
      }
      const next = afterArchive.filter((c) => c.id !== id);
      writeIndex(next);
      setConversations(next);
      window.dispatchEvent(new Event(ACTIVE_CHANGED_EVENT));
    },
    [archiveActive],
  );

  const remove = useCallback((id: string) => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.removeItem(`${CONV_PREFIX}${id}`);
    } catch {
      // ignore
    }
    const next = readIndex().filter((c) => c.id !== id);
    writeIndex(next);
    setConversations(next);
  }, []);

  return { conversations, newChat, load, remove };
}

function updateLastAssistant(
  list: ChatTurn[],
  updater: (turn: ChatTurn) => ChatTurn,
): ChatTurn[] {
  const idx = [...list].reverse().findIndex((m) => m.role === "assistant");
  if (idx === -1) return list;
  const realIdx = list.length - 1 - idx;
  const target = list[realIdx];
  if (!target) return list;
  const next = [...list];
  next[realIdx] = updater(target);
  return next;
}

interface ParsedEvent {
  event: string;
  data: Record<string, unknown> & { text?: string };
}

function parseSSEBlock(block: string): ParsedEvent | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const raw of block.split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith(":")) continue;
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (!dataLines.length) return null;
  try {
    const parsed = JSON.parse(dataLines.join("\n"));
    return { event, data: parsed };
  } catch {
    return { event, data: { text: dataLines.join("\n") } };
  }
}
