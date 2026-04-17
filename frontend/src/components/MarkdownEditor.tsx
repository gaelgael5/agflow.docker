import { useRef, useState, type ChangeEvent } from "react";
import { useTranslation } from "react-i18next";
import {
  Bold,
  Code,
  Heading1,
  Heading2,
  Heading3,
  HelpCircle,
  Italic,
  Link,
  List,
  ListOrdered,
  Quote,
} from "lucide-react";

interface Props {
  value: string;
  onChange: (value: string) => void;
  readOnly?: boolean;
  placeholder?: string;
  minHeight?: number;
  /** When true, the textarea grows to fill its parent's height (flex: 1). */
  fill?: boolean;
}

function insertMarkdown(
  textarea: HTMLTextAreaElement,
  value: string,
  onChange: (v: string) => void,
  before: string,
  after: string,
  defaultText?: string,
) {
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const selected = value.slice(start, end) || defaultText || "";
  const replacement = before + selected + after;
  const next = value.slice(0, start) + replacement + value.slice(end);
  onChange(next);
  requestAnimationFrame(() => {
    textarea.focus();
    const cursorPos = start + before.length + selected.length;
    textarea.setSelectionRange(
      start + before.length,
      cursorPos,
    );
  });
}

function prefixLines(
  textarea: HTMLTextAreaElement,
  value: string,
  onChange: (v: string) => void,
  prefix: string,
) {
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const lineStart = value.lastIndexOf("\n", start - 1) + 1;
  const lineEnd = value.indexOf("\n", end);
  const block = value.slice(lineStart, lineEnd === -1 ? undefined : lineEnd);
  const prefixed = block
    .split("\n")
    .map((line) => prefix + line)
    .join("\n");
  const next = value.slice(0, lineStart) + prefixed + (lineEnd === -1 ? "" : value.slice(lineEnd));
  onChange(next);
  requestAnimationFrame(() => {
    textarea.focus();
  });
}

interface ToolbarButton {
  icon: React.ReactNode;
  title: string;
  action: (
    textarea: HTMLTextAreaElement,
    value: string,
    onChange: (v: string) => void,
  ) => void;
}

export function MarkdownEditor({
  value,
  onChange,
  readOnly = false,
  placeholder,
  minHeight = 240,
  fill = false,
}: Props) {
  const { t } = useTranslation();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [showHelp, setShowHelp] = useState(false);

  function handleChange(e: ChangeEvent<HTMLTextAreaElement>) {
    onChange(e.target.value);
  }

  const buttons: ToolbarButton[] = [
    {
      icon: <Bold className="w-3.5 h-3.5" />,
      title: t("markdown.bold"),
      action: (ta, v, cb) => insertMarkdown(ta, v, cb, "**", "**", "texte"),
    },
    {
      icon: <Italic className="w-3.5 h-3.5" />,
      title: t("markdown.italic"),
      action: (ta, v, cb) => insertMarkdown(ta, v, cb, "*", "*", "texte"),
    },
    {
      icon: <Heading1 className="w-3.5 h-3.5" />,
      title: t("markdown.h1"),
      action: (ta, v, cb) => prefixLines(ta, v, cb, "# "),
    },
    {
      icon: <Heading2 className="w-3.5 h-3.5" />,
      title: t("markdown.h2"),
      action: (ta, v, cb) => prefixLines(ta, v, cb, "## "),
    },
    {
      icon: <Heading3 className="w-3.5 h-3.5" />,
      title: t("markdown.h3"),
      action: (ta, v, cb) => prefixLines(ta, v, cb, "### "),
    },
    {
      icon: <List className="w-3.5 h-3.5" />,
      title: t("markdown.ul"),
      action: (ta, v, cb) => prefixLines(ta, v, cb, "- "),
    },
    {
      icon: <ListOrdered className="w-3.5 h-3.5" />,
      title: t("markdown.ol"),
      action: (ta, v, cb) => prefixLines(ta, v, cb, "1. "),
    },
    {
      icon: <Quote className="w-3.5 h-3.5" />,
      title: t("markdown.quote"),
      action: (ta, v, cb) => prefixLines(ta, v, cb, "> "),
    },
    {
      icon: <Code className="w-3.5 h-3.5" />,
      title: t("markdown.code"),
      action: (ta, v, cb) => insertMarkdown(ta, v, cb, "`", "`", "code"),
    },
    {
      icon: <Link className="w-3.5 h-3.5" />,
      title: t("markdown.link"),
      action: (ta, v, cb) => insertMarkdown(ta, v, cb, "[", "](url)", "texte"),
    },
  ];

  return (
    <div className={fill ? "flex flex-col flex-1 min-h-0" : ""}>
      {!readOnly && (
        <div className="flex items-center gap-0.5 mb-1 flex-wrap">
          {buttons.map((btn) => (
            <button
              key={btn.title}
              type="button"
              title={btn.title}
              className="p-1.5 rounded hover:bg-secondary text-muted-foreground hover:text-foreground transition-colors"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => {
                if (textareaRef.current) {
                  btn.action(textareaRef.current, value, onChange);
                }
              }}
            >
              {btn.icon}
            </button>
          ))}
          <div className="flex-1" />
          <button
            type="button"
            title={t("markdown.help")}
            className={`p-1.5 rounded transition-colors ${showHelp ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-secondary hover:text-foreground"}`}
            onClick={() => setShowHelp((v) => !v)}
          >
            <HelpCircle className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {showHelp && !readOnly && (
        <div className="rounded-md bg-muted p-3 mb-2 text-[12px] overflow-y-auto max-h-40">
          <table className="w-full text-left">
            <tbody className="font-mono">
              <tr className="border-b border-muted-foreground/20">
                <td className="py-0.5 pr-4 text-primary">**{t("markdown.bold")}**</td>
                <td className="py-0.5 font-sans">{t("markdown.bold")}</td>
              </tr>
              <tr className="border-b border-muted-foreground/20">
                <td className="py-0.5 pr-4 text-primary">*{t("markdown.italic")}*</td>
                <td className="py-0.5 font-sans">{t("markdown.italic")}</td>
              </tr>
              <tr className="border-b border-muted-foreground/20">
                <td className="py-0.5 pr-4 text-primary"># Titre 1</td>
                <td className="py-0.5 font-sans">{t("markdown.h1")}</td>
              </tr>
              <tr className="border-b border-muted-foreground/20">
                <td className="py-0.5 pr-4 text-primary">## Titre 2</td>
                <td className="py-0.5 font-sans">{t("markdown.h2")}</td>
              </tr>
              <tr className="border-b border-muted-foreground/20">
                <td className="py-0.5 pr-4 text-primary">- item</td>
                <td className="py-0.5 font-sans">{t("markdown.ul")}</td>
              </tr>
              <tr className="border-b border-muted-foreground/20">
                <td className="py-0.5 pr-4 text-primary">1. item</td>
                <td className="py-0.5 font-sans">{t("markdown.ol")}</td>
              </tr>
              <tr className="border-b border-muted-foreground/20">
                <td className="py-0.5 pr-4 text-primary">&gt; citation</td>
                <td className="py-0.5 font-sans">{t("markdown.quote")}</td>
              </tr>
              <tr className="border-b border-muted-foreground/20">
                <td className="py-0.5 pr-4 text-primary">`code`</td>
                <td className="py-0.5 font-sans">{t("markdown.code")}</td>
              </tr>
              <tr className="border-b border-muted-foreground/20">
                <td className="py-0.5 pr-4 text-primary">```bloc```</td>
                <td className="py-0.5 font-sans">{t("markdown.code_block")}</td>
              </tr>
              <tr>
                <td className="py-0.5 pr-4 text-primary">[texte](url)</td>
                <td className="py-0.5 font-sans">{t("markdown.link")}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}

      <textarea
        ref={textareaRef}
        value={value}
        onChange={handleChange}
        disabled={readOnly}
        placeholder={placeholder}
        style={{
          width: "100%",
          minHeight: `${minHeight}px`,
          flex: fill ? 1 : undefined,
          fontFamily: "ui-monospace, SFMono-Regular, monospace",
          fontSize: "13px",
          padding: "0.75rem",
          border: "1px solid #ccc",
          borderRadius: "4px",
          resize: fill ? "none" : "vertical",
        }}
      />
    </div>
  );
}
