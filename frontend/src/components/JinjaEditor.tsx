import { useEffect, useRef } from "react";
import { EditorView, keymap } from "@codemirror/view";
import { EditorState } from "@codemirror/state";
import { html } from "@codemirror/lang-html";
import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import {
  bracketMatching,
  defaultHighlightStyle,
  syntaxHighlighting,
} from "@codemirror/language";

const agflowTheme = EditorView.theme({
  "&": {
    backgroundColor: "hsl(var(--background))",
    color: "hsl(var(--foreground))",
  },
  ".cm-gutters": {
    backgroundColor: "hsl(var(--muted))",
    color: "hsl(var(--muted-foreground))",
    borderRight: "1px solid hsl(var(--border))",
  },
  ".cm-activeLineGutter": {
    backgroundColor: "hsl(var(--accent))",
  },
  ".cm-activeLine": {
    backgroundColor: "hsl(var(--accent) / 0.3)",
  },
  ".cm-cursor": {
    borderLeftColor: "hsl(var(--primary))",
  },
  ".cm-selectionBackground, &.cm-focused .cm-selectionBackground": {
    backgroundColor: "hsl(var(--primary) / 0.2) !important",
  },
});

interface Props {
  value: string;
  onChange: (value: string) => void;
  readOnly?: boolean;
}

export function JinjaEditor({ value, onChange, readOnly = false }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    if (!containerRef.current) return;

    const state = EditorState.create({
      doc: value,
      extensions: [
        html(),
        syntaxHighlighting(defaultHighlightStyle),
        agflowTheme,
        history(),
        bracketMatching(),
        keymap.of([...defaultKeymap, ...historyKeymap]),
        EditorView.lineWrapping,
        EditorView.editable.of(!readOnly),
        EditorView.updateListener.of((update) => {
          if (update.docChanged) {
            onChangeRef.current(update.state.doc.toString());
          }
        }),
      ],
    });

    const view = new EditorView({ state, parent: containerRef.current });
    viewRef.current = view;

    return () => {
      view.destroy();
      viewRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [readOnly]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    const current = view.state.doc.toString();
    if (current !== value) {
      view.dispatch({
        changes: { from: 0, to: current.length, insert: value },
      });
    }
  }, [value]);

  return (
    <div
      ref={containerRef}
      className="border rounded-md overflow-hidden flex-1 min-h-[240px]"
      style={{ fontSize: "13px" }}
    />
  );
}
