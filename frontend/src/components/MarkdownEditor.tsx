import type { ChangeEvent } from "react";

interface Props {
  value: string;
  onChange: (value: string) => void;
  readOnly?: boolean;
  placeholder?: string;
  minHeight?: number;
  /** When true, the textarea grows to fill its parent's height (flex: 1). */
  fill?: boolean;
}

export function MarkdownEditor({
  value,
  onChange,
  readOnly = false,
  placeholder,
  minHeight = 240,
  fill = false,
}: Props) {
  function handleChange(e: ChangeEvent<HTMLTextAreaElement>) {
    onChange(e.target.value);
  }

  return (
    <textarea
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
  );
}
