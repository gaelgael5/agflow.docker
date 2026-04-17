import { useEffect, useRef } from "react";
import { EditorView, keymap, lineNumbers, Decoration, ViewPlugin, type DecorationSet, type ViewUpdate } from "@codemirror/view";
import { EditorState, RangeSetBuilder } from "@codemirror/state";
import { markdown } from "@codemirror/lang-markdown";
import { oneDarkHighlightStyle } from "@codemirror/theme-one-dark";
import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { bracketMatching, syntaxHighlighting } from "@codemirror/language";

// Custom Jinja2 delimiter highlighting
const jinjaExprMark = Decoration.mark({ class: "cm-jinja-expr" });
const jinjaStmtMark = Decoration.mark({ class: "cm-jinja-stmt" });
const jinjaCommentMark = Decoration.mark({ class: "cm-jinja-comment" });

function buildJinjaDecorations(view: EditorView): DecorationSet {
  const builder = new RangeSetBuilder<Decoration>();
  const doc = view.state.doc.toString();
  const patterns: Array<{ re: RegExp; mark: Decoration }> = [
    { re: /\{\{.*?\}\}/g, mark: jinjaExprMark },
    { re: /\{%.*?%\}/g, mark: jinjaStmtMark },
    { re: /\{#.*?#\}/g, mark: jinjaCommentMark },
  ];
  const all: Array<{ from: number; to: number; mark: Decoration }> = [];
  for (const { re, mark } of patterns) {
    let m;
    while ((m = re.exec(doc)) !== null) {
      all.push({ from: m.index, to: m.index + m[0].length, mark });
    }
  }
  all.sort((a, b) => a.from - b.from);
  for (const { from, to, mark } of all) {
    builder.add(from, to, mark);
  }
  return builder.finish();
}

const jinjaHighlighter = ViewPlugin.fromClass(
  class {
    decorations: DecorationSet;
    constructor(view: EditorView) {
      this.decorations = buildJinjaDecorations(view);
    }
    update(update: ViewUpdate) {
      if (update.docChanged || update.viewportChanged) {
        this.decorations = buildJinjaDecorations(update.view);
      }
    }
  },
  { decorations: (v) => v.decorations },
);

const jinjaStyles = EditorView.baseTheme({
  ".cm-jinja-expr": {
    color: "#e5c07b",
    fontWeight: "bold",
  },
  ".cm-jinja-stmt": {
    color: "#c678dd",
    fontWeight: "bold",
  },
  ".cm-jinja-comment": {
    color: "#5c6370",
    fontStyle: "italic",
  },
});

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
        markdown(),
        syntaxHighlighting(oneDarkHighlightStyle),
        jinjaHighlighter,
        jinjaStyles,
        agflowTheme,
        lineNumbers(),
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
