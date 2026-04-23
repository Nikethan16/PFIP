"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const STORAGE_KEY = "pfip:chat:messages:v1";

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
  const [messages, setMessages] = useState<ChatTurn[]>(() => {
    if (typeof window === "undefined") return [];
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw) as ChatTurn[];
      // Drop any message still flagged "pending" — those never completed.
      return parsed.map((m) => ({ ...m, pending: false }));
    } catch {
      return [];
    }
  });
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

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
