"use client";

import * as React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";

import { cn } from "@/lib/utils";

/**
 * Shared markdown renderer with GFM tables + code highlighting. Used by the
 * morning brief and chat assistant messages.
 *
 * We explicitly don't render raw HTML — that stays disabled to avoid XSS
 * from upstream news sources or KB docs.
 */
export function Markdown({
  children,
  className,
}: {
  children: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "prose prose-sm max-w-none break-words dark:prose-invert",
        "prose-pre:bg-muted prose-pre:text-xs prose-pre:p-3",
        "prose-code:text-xs prose-code:bg-muted prose-code:rounded prose-code:px-1 prose-code:py-0.5",
        "prose-headings:font-semibold prose-headings:mt-4 prose-headings:mb-2",
        "prose-p:my-2 prose-ul:my-2 prose-li:my-0",
        "prose-a:text-primary prose-a:underline",
        className,
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
