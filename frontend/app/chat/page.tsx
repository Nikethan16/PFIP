import { MessageStream } from "@/components/agent/message-stream";

export default function ChatPage() {
  return (
    <div className="flex h-[calc(100dvh-12rem)] flex-col md:h-[calc(100dvh-7rem)]">
      <div className="mb-2">
        <h1 className="text-2xl font-bold tracking-tight">Chat</h1>
        <p className="text-sm text-muted-foreground">
          Ask PFIP anything. Responses cite the portfolio, knowledge base, and
          live news.
        </p>
      </div>
      <div className="flex-1 overflow-hidden rounded-lg border bg-card p-3">
        <MessageStream />
      </div>
    </div>
  );
}
