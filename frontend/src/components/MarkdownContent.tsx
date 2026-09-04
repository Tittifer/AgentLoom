import type { ReactNode } from "react";

interface MarkdownContentProps {
  content: string;
  trailing?: ReactNode;
}

type TextAlignment = "left" | "center" | "right";

export function MarkdownContent({ content, trailing }: MarkdownContentProps) {
  return (
    <div className="markdown-content">
      {renderBlocks(content)}
      {trailing}
    </div>
  );
}

function renderBlocks(content: string): ReactNode[] {
  const lines = content.replace(/\r\n?/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }

    const fence = line.match(/^\s*```([^`]*)$/);
    if (fence) {
      const code: string[] = [];
      index += 1;
      while (index < lines.length && !/^\s*```\s*$/.test(lines[index])) {
        code.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      const language = fence[1].trim();
      blocks.push(
        <pre className="markdown-code-block" key={`code-${index}`}>
          <code className={language ? `language-${language}` : undefined}>{code.join("\n")}</code>
        </pre>,
      );
      continue;
    }

    const heading = line.match(/^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/);
    if (heading) {
      const level = heading[1].length as 1 | 2 | 3 | 4 | 5 | 6;
      const Heading = `h${level}` as "h1" | "h2" | "h3" | "h4" | "h5" | "h6";
      blocks.push(
        <Heading key={`heading-${index}`}>{renderInline(heading[2], `heading-${index}`)}</Heading>,
      );
      index += 1;
      continue;
    }

    if (isHorizontalRule(line)) {
      blocks.push(<hr key={`rule-${index}`} />);
      index += 1;
      continue;
    }

    if (isTableStart(lines, index)) {
      const headers = splitTableRow(line);
      const alignments = splitTableRow(lines[index + 1]).map(tableAlignment);
      const rows: string[][] = [];
      index += 2;
      while (index < lines.length && isTableRow(lines[index])) {
        rows.push(splitTableRow(lines[index]));
        index += 1;
      }
      blocks.push(
        <div className="markdown-table-wrap" key={`table-${index}`}>
          <table>
            <thead>
              <tr>
                {headers.map((cell, cellIndex) => (
                  <th key={`header-${cellIndex}`} style={{ textAlign: alignments[cellIndex] ?? "left" }}>
                    {renderInline(cell, `header-${cellIndex}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={`row-${rowIndex}`}>
                  {headers.map((_, cellIndex) => (
                    <td key={`cell-${cellIndex}`} style={{ textAlign: alignments[cellIndex] ?? "left" }}>
                      {renderInline(row[cellIndex] ?? "", `row-${rowIndex}-cell-${cellIndex}`)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }

    const unordered = line.match(/^\s*[-+*]\s+(.+)$/);
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (unordered || ordered) {
      const orderedList = Boolean(ordered);
      const items: string[] = [];
      while (index < lines.length) {
        const item = lines[index].match(
          orderedList ? /^\s*\d+[.)]\s+(.+)$/ : /^\s*[-+*]\s+(.+)$/,
        );
        if (!item) break;
        items.push(item[1]);
        index += 1;
      }
      const List = orderedList ? "ol" : "ul";
      blocks.push(
        <List key={`list-${index}`}>
          {items.map((item, itemIndex) => (
            <li key={`item-${itemIndex}`}>{renderInline(item, `item-${itemIndex}`)}</li>
          ))}
        </List>,
      );
      continue;
    }

    if (/^\s*>/.test(line)) {
      const quote: string[] = [];
      while (index < lines.length) {
        const quotedLine = lines[index].match(/^\s*>\s?(.*)$/);
        if (!quotedLine) break;
        quote.push(quotedLine[1]);
        index += 1;
      }
      blocks.push(
        <blockquote key={`quote-${index}`}>{renderInline(quote.join("\n"), `quote-${index}`)}</blockquote>,
      );
      continue;
    }

    const paragraph: string[] = [];
    while (index < lines.length && lines[index].trim() && !isBlockStart(lines, index)) {
      paragraph.push(lines[index]);
      index += 1;
    }
    if (paragraph.length === 0) {
      paragraph.push(line);
      index += 1;
    }
    blocks.push(
      <p key={`paragraph-${index}`}>{renderInline(paragraph.join("\n"), `paragraph-${index}`)}</p>,
    );
  }

  return blocks;
}

function isBlockStart(lines: string[], index: number): boolean {
  const line = lines[index];
  return (
    /^\s*```/.test(line) ||
    /^\s{0,3}#{1,6}\s+/.test(line) ||
    isHorizontalRule(line) ||
    isTableStart(lines, index) ||
    /^\s*[-+*]\s+/.test(line) ||
    /^\s*\d+[.)]\s+/.test(line) ||
    /^\s*>/.test(line)
  );
}

function isHorizontalRule(line: string): boolean {
  return /^\s{0,3}(?:(?:-\s*){3,}|(?:\*\s*){3,}|(?:_\s*){3,})$/.test(line);
}

function isTableStart(lines: string[], index: number): boolean {
  return (
    index + 1 < lines.length &&
    isTableRow(lines[index]) &&
    isTableRow(lines[index + 1]) &&
    splitTableRow(lines[index + 1]).every((cell) => /^:?-{3,}:?$/.test(cell.trim()))
  );
}

function isTableRow(line: string): boolean {
  return line.includes("|") && splitTableRow(line).length > 1;
}

function splitTableRow(line: string): string[] {
  let source = line.trim();
  if (source.startsWith("|")) source = source.slice(1);
  if (source.endsWith("|")) source = source.slice(0, -1);

  const cells: string[] = [];
  let cell = "";
  for (let index = 0; index < source.length; index += 1) {
    if (source[index] === "\\" && source[index + 1] === "|") {
      cell += "|";
      index += 1;
    } else if (source[index] === "|") {
      cells.push(cell.trim());
      cell = "";
    } else {
      cell += source[index];
    }
  }
  cells.push(cell.trim());
  return cells;
}

function tableAlignment(separator: string): TextAlignment {
  const value = separator.trim();
  if (value.startsWith(":") && value.endsWith(":")) return "center";
  if (value.endsWith(":")) return "right";
  return "left";
}

function renderInline(content: string, keyPrefix: string): ReactNode[] {
  const tokens: ReactNode[] = [];
  const pattern = /(`[^`\n]+`|\*\*[^*\n]+\*\*|__[^_\n]+__|~~[^~\n]+~~|\[[^\]\n]+\]\((?:[^()\s]|\([^()\s]*\))+\)|\*[^*\n]+\*|_[^_\n]+_|\n)/g;
  let cursor = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(content)) !== null) {
    if (match.index > cursor) tokens.push(content.slice(cursor, match.index));
    const value = match[0];
    const key = `${keyPrefix}-${match.index}`;

    if (value === "\n") {
      tokens.push(<br key={key} />);
    } else if (value.startsWith("`")) {
      tokens.push(<code key={key}>{value.slice(1, -1)}</code>);
    } else if (value.startsWith("**") || value.startsWith("__")) {
      tokens.push(<strong key={key}>{renderInline(value.slice(2, -2), `${key}-strong`)}</strong>);
    } else if (value.startsWith("~~")) {
      tokens.push(<del key={key}>{renderInline(value.slice(2, -2), `${key}-del`)}</del>);
    } else if (value.startsWith("[") && value.includes("](")) {
      const separator = value.indexOf("](");
      const label = value.slice(1, separator);
      const href = safeHref(value.slice(separator + 2, -1));
      tokens.push(
        href ? (
          <a href={href} key={key} rel="noreferrer" target="_blank">
            {label}
          </a>
        ) : (
          label
        ),
      );
    } else {
      tokens.push(<em key={key}>{renderInline(value.slice(1, -1), `${key}-em`)}</em>);
    }
    cursor = pattern.lastIndex;
  }

  if (cursor < content.length) tokens.push(content.slice(cursor));
  return tokens;
}

function safeHref(href: string): string | null {
  if (/^(?:https?:|mailto:)/i.test(href)) return href;
  if (/^(?:#|\/|\.\/|\.\.\/)/.test(href)) return href;
  return null;
}
