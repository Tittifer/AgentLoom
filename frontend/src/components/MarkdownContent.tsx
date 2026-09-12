import type { ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

interface MarkdownContentProps {
  content: string;
  trailing?: ReactNode;
}

const components: Components = {
  a: ({ children, href }) => {
    const safe = href ? safeHref(href) : null;
    return safe ? (
      <a href={safe} rel="noreferrer" target="_blank">
        {children}
      </a>
    ) : (
      <>{children}</>
    );
  },
  pre: ({ children }) => <pre className="markdown-code-block">{children}</pre>,
  table: ({ children }) => (
    <div className="markdown-table-wrap">
      <table>{children}</table>
    </div>
  ),
  img: ({ alt }) => <span>{alt ?? ""}</span>,
};

export function MarkdownContent({ content, trailing }: MarkdownContentProps) {
  return (
    <div className="markdown-content">
      <ReactMarkdown
        components={components}
        remarkPlugins={[remarkGfm]}
        urlTransform={(url) => safeHref(url) ?? ""}
      >
        {content}
      </ReactMarkdown>
      {trailing}
    </div>
  );
}

function safeHref(href: string): string | null {
  if (/^(?:https?:|mailto:)/i.test(href)) return href;
  if (/^(?:#|\/|\.\/|\.\.\/)/.test(href)) return href;
  return null;
}
