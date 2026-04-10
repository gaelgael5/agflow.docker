import type { ChangeEvent } from "react";

interface Props {
  value: string;
  onChange: (value: string) => void;
  readOnly?: boolean;
  placeholder?: string;
  minHeight?: number;
}

export function MarkdownEditor({
  value,
  onChange,
  readOnly = false,
  placeholder,
  minHeight = 240,
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
        fontFamily: "ui-monospace, SFMono-Regular, monospace",
        fontSize: "13px",
        padding: "0.75rem",
        border: "1px solid #ccc",
        borderRadius: "4px",
        resize: "vertical",
      }}
    />
  );
}
