import { useLayoutEffect, useMemo, useRef, type ChangeEvent } from "react";
import {
  detectLanguage,
  highlight,
  type Language,
} from "@/lib/codeHighlight";

interface Props {
  value: string;
  onChange: (value: string) => void;
  readOnly?: boolean;
  placeholder?: string;
  minHeight?: number;
  /** When true, the editor grows to fill its parent's height (flex: 1). */
  fill?: boolean;
  /** Override the auto-detected language. */
  language?: Language;
  /** File path — used to auto-detect language when `language` is not set. */
  path?: string;
}

const PADDING_X = 12; // px — horizontal padding of the text areas
const GUTTER_PADDING_RIGHT = 8; // px — space between digits and code

export function CodeEditor({
  value,
  onChange,
  readOnly = false,
  placeholder,
  minHeight = 240,
  fill = false,
  language,
  path,
}: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const preRef = useRef<HTMLPreElement>(null);
  const gutterRef = useRef<HTMLPreElement>(null);

  const effectiveLanguage: Language =
    language ?? (path ? detectLanguage(path) : "plain");

  const tokens = useMemo(
    () => highlight(value, effectiveLanguage),
    [value, effectiveLanguage],
  );

  // Count visible lines. split("\n") returns N + 1 items when value ends
  // with "\n", which matches the editor's behaviour of showing the trailing
  // empty line where the cursor will land.
  const lineCount = useMemo(
    () => Math.max(1, value.length === 0 ? 1 : value.split("\n").length),
    [value],
  );
  const gutterDigits = Math.max(2, String(lineCount).length);
  // Each monospace digit ≈ 0.6em at 13px, give a little headroom.
  const gutterWidthPx = Math.round(gutterDigits * 0.6 * 13) + GUTTER_PADDING_RIGHT * 2;

  // Keep the highlighted <pre> and gutter <pre> scrolled in sync with the
  // editable textarea. The gutter only follows vertical scroll.
  useLayoutEffect(() => {
    const ta = textareaRef.current;
    const pre = preRef.current;
    const gutter = gutterRef.current;
    if (!ta || !pre) return;
    const onScroll = () => {
      pre.scrollTop = ta.scrollTop;
      pre.scrollLeft = ta.scrollLeft;
      if (gutter) gutter.scrollTop = ta.scrollTop;
    };
    ta.addEventListener("scroll", onScroll);
    return () => ta.removeEventListener("scroll", onScroll);
  }, []);

  function handleChange(e: ChangeEvent<HTMLTextAreaElement>) {
    onChange(e.target.value);
  }

  // Empty trailing newline trick: textareas shrink the last empty line out,
  // but a <pre> keeps it. Appending a newline keeps both views aligned when
  // the source ends with "\n".
  const tokensToRender =
    value.endsWith("\n") || value.length === 0
      ? [...tokens, { text: " ", cls: "" }]
      : tokens;

  const containerStyle: React.CSSProperties = {
    position: "relative",
    width: "100%",
    minHeight: `${minHeight}px`,
    flex: fill ? 1 : undefined,
    display: "flex",
  };

  const sharedTextStyle: React.CSSProperties = {
    margin: 0,
    paddingTop: `${PADDING_X}px`,
    paddingBottom: `${PADDING_X}px`,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "13px",
    lineHeight: "1.5",
    whiteSpace: "pre",
    overflowWrap: "normal",
    wordBreak: "normal",
    tabSize: 2,
  };

  // Pre + textarea sit to the right of the gutter.
  const codeLeft = `${gutterWidthPx}px`;

  return (
    <div
      style={containerStyle}
      className="rounded-md border bg-zinc-950 overflow-hidden"
    >
      {/* Line-number gutter */}
      <pre
        ref={gutterRef}
        aria-hidden
        style={{
          ...sharedTextStyle,
          position: "absolute",
          top: 0,
          bottom: 0,
          left: 0,
          width: `${gutterWidthPx}px`,
          paddingLeft: `${GUTTER_PADDING_RIGHT}px`,
          paddingRight: `${GUTTER_PADDING_RIGHT}px`,
          overflow: "hidden",
          textAlign: "right",
          color: "#52525b", // zinc-600
          pointerEvents: "none",
          userSelect: "none",
          borderRight: "1px solid #27272a", // zinc-800
          background: "#0a0a0a",
        }}
      >
        {Array.from({ length: lineCount }, (_, i) => `${i + 1}\n`).join("")}
      </pre>

      {/* Syntax-highlighted code overlay */}
      <pre
        ref={preRef}
        aria-hidden
        style={{
          ...sharedTextStyle,
          position: "absolute",
          top: 0,
          right: 0,
          bottom: 0,
          left: codeLeft,
          paddingLeft: `${PADDING_X}px`,
          paddingRight: `${PADDING_X}px`,
          overflow: "auto",
          pointerEvents: "none",
          color: "#e4e4e7",
        }}
      >
        {tokensToRender.map((tok, i) => (
          <span key={i} className={tok.cls}>
            {tok.text}
          </span>
        ))}
      </pre>

      {/* Transparent editable textarea on top */}
      <textarea
        ref={textareaRef}
        value={value}
        onChange={handleChange}
        disabled={readOnly}
        placeholder={placeholder}
        spellCheck={false}
        style={{
          ...sharedTextStyle,
          position: "absolute",
          top: 0,
          right: 0,
          bottom: 0,
          left: codeLeft,
          paddingLeft: `${PADDING_X}px`,
          paddingRight: `${PADDING_X}px`,
          width: `calc(100% - ${codeLeft})`,
          height: "100%",
          resize: "none",
          background: "transparent",
          color: "transparent",
          caretColor: "#e4e4e7",
          border: "none",
          outline: "none",
          overflow: "auto",
        }}
      />
    </div>
  );
}
