import { useState } from "react";
import { ChevronRight, FileCode2, FilePlus, Folder, FolderOpen, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";

interface FileEntry {
  id: string;
  path: string;
}

interface TreeNode {
  name: string;
  fullPath: string;
  file?: FileEntry;
  children: TreeNode[];
}

function buildTree(files: FileEntry[]): TreeNode[] {
  const root: TreeNode[] = [];

  for (const file of files) {
    const parts = file.path.split("/");
    let current = root;

    for (let i = 0; i < parts.length; i++) {
      const name = parts[i]!;
      const isFile = i === parts.length - 1;
      const fullPath = parts.slice(0, i + 1).join("/");

      let node = current.find((n) => n.name === name && !n.file === !isFile);
      if (!node) {
        node = {
          name,
          fullPath,
          file: isFile ? file : undefined,
          children: [],
        };
        current.push(node);
      }
      current = node.children;
    }
  }

  return sortNodes(root);
}

function sortNodes(nodes: TreeNode[]): TreeNode[] {
  const dirs = nodes.filter((n) => !n.file).sort((a, b) => a.name.localeCompare(b.name));
  const files = nodes.filter((n) => n.file).sort((a, b) => a.name.localeCompare(b.name));
  for (const d of dirs) {
    d.children = sortNodes(d.children);
  }
  return [...dirs, ...files];
}

// ─── Props ────────────────────────────────────────────────────────────────────

export interface FileTreeProps {
  files: FileEntry[];
  selectedId: string | null;
  onSelect: (fileId: string) => void;
  onAddFileInFolder?: (folderPath: string) => void;
  onDeleteFolder?: (folderPath: string) => void;
  protectedFiles?: readonly string[];
}

export function FileTree({
  files,
  selectedId,
  onSelect,
  onAddFileInFolder,
  onDeleteFolder,
  protectedFiles = [],
}: FileTreeProps) {
  const tree = buildTree(files);
  return (
    <ul className="space-y-0.5">
      {tree.map((node) => (
        <TreeItem
          key={node.fullPath}
          node={node}
          depth={0}
          selectedId={selectedId}
          onSelect={onSelect}
          onAddFileInFolder={onAddFileInFolder}
          onDeleteFolder={onDeleteFolder}
          protectedFiles={protectedFiles}
        />
      ))}
    </ul>
  );
}

// ─── Tree Item ────────────────────────────────────────────────────────────────

interface TreeItemProps {
  node: TreeNode;
  depth: number;
  selectedId: string | null;
  onSelect: (fileId: string) => void;
  onAddFileInFolder?: (folderPath: string) => void;
  onDeleteFolder?: (folderPath: string) => void;
  protectedFiles: readonly string[];
}

function TreeItem({
  node,
  depth,
  selectedId,
  onSelect,
  onAddFileInFolder,
  onDeleteFolder,
  protectedFiles,
}: TreeItemProps) {
  const [open, setOpen] = useState(true);
  const indent = depth * 12;

  if (node.file) {
    const active = selectedId === node.file.id;
    return (
      <li>
        <button
          type="button"
          onClick={() => onSelect(node.file!.id)}
          style={{ paddingLeft: `${indent + 8}px` }}
          className={cn(
            "w-full text-left pr-2 py-1 rounded-md font-mono text-[12px] flex items-center gap-1.5 transition-colors",
            active
              ? "bg-primary/10 text-primary"
              : "hover:bg-secondary text-foreground",
          )}
        >
          <FileCode2 className="w-3.5 h-3.5 shrink-0 text-muted-foreground" />
          <span className="truncate">{node.name}</span>
        </button>
      </li>
    );
  }

  const isProtected = node.children.some(
    (c) => c.file && protectedFiles.includes(c.file.path),
  );

  return (
    <li>
      <div className="group flex items-center">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          style={{ paddingLeft: `${indent + 4}px` }}
          className="flex-1 text-left pr-1 py-1 rounded-md text-[12px] flex items-center gap-1 hover:bg-secondary/60 text-muted-foreground transition-colors"
        >
          <ChevronRight
            className={cn(
              "w-3 h-3 shrink-0 transition-transform",
              open && "rotate-90",
            )}
          />
          {open ? (
            <FolderOpen className="w-3.5 h-3.5 shrink-0 text-amber-500/80" />
          ) : (
            <Folder className="w-3.5 h-3.5 shrink-0 text-amber-500/80" />
          )}
          <span className="truncate font-medium">{node.name}</span>
        </button>
        <div className="hidden group-hover:flex gap-0.5 pr-1">
          {onAddFileInFolder && (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onAddFileInFolder(node.fullPath); }}
              className="p-0.5 rounded hover:bg-secondary"
              title="New file"
            >
              <FilePlus className="w-3 h-3 text-muted-foreground" />
            </button>
          )}
          {onDeleteFolder && !isProtected && (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onDeleteFolder(node.fullPath); }}
              className="p-0.5 rounded hover:bg-secondary"
              title="Delete folder"
            >
              <Trash2 className="w-3 h-3 text-destructive" />
            </button>
          )}
        </div>
      </div>
      {open && (
        <ul className="space-y-0.5">
          {node.children.map((child) => (
            <TreeItem
              key={child.fullPath}
              node={child}
              depth={depth + 1}
              selectedId={selectedId}
              onSelect={onSelect}
              onAddFileInFolder={onAddFileInFolder}
              onDeleteFolder={onDeleteFolder}
              protectedFiles={protectedFiles}
            />
          ))}
        </ul>
      )}
    </li>
  );
}
