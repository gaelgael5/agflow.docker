import { describe, it, expect, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useSectionDropzone } from "@/hooks/useSectionDropzone";

function makeDragEvent(type: string, files: File[] = []): unknown {
  return {
    type,
    preventDefault: vi.fn(),
    stopPropagation: vi.fn(),
    dataTransfer: { files, types: ["Files"] },
  };
}

describe("useSectionDropzone", () => {
  it("is not dragOver initially", () => {
    const onFiles = vi.fn();
    const { result } = renderHook(() => useSectionDropzone(onFiles));
    expect(result.current.isDragOver).toBe(false);
  });

  it("sets isDragOver on dragenter with Files", () => {
    const onFiles = vi.fn();
    const { result } = renderHook(() => useSectionDropzone(onFiles));
    act(() => {
      result.current.dropzoneProps.onDragEnter(makeDragEvent("dragenter") as never);
    });
    expect(result.current.isDragOver).toBe(true);
  });

  it("clears isDragOver on dragleave", () => {
    const onFiles = vi.fn();
    const { result } = renderHook(() => useSectionDropzone(onFiles));
    act(() => {
      result.current.dropzoneProps.onDragEnter(makeDragEvent("dragenter") as never);
    });
    act(() => {
      result.current.dropzoneProps.onDragLeave(makeDragEvent("dragleave") as never);
    });
    expect(result.current.isDragOver).toBe(false);
  });

  it("calls onFiles on drop with the FileList and clears state", () => {
    const onFiles = vi.fn();
    const files = [new File(["# hi"], "a.md")];
    const { result } = renderHook(() => useSectionDropzone(onFiles));
    act(() => {
      result.current.dropzoneProps.onDrop(makeDragEvent("drop", files) as never);
    });
    expect(onFiles).toHaveBeenCalledTimes(1);
    expect(onFiles).toHaveBeenCalledWith(files);
    expect(result.current.isDragOver).toBe(false);
  });

  it("calls preventDefault on dragover to enable drop", () => {
    const onFiles = vi.fn();
    const { result } = renderHook(() => useSectionDropzone(onFiles));
    const evt = makeDragEvent("dragover");
    act(() => {
      result.current.dropzoneProps.onDragOver(evt as never);
    });
    expect((evt as { preventDefault: () => void }).preventDefault).toHaveBeenCalled();
  });
});
