import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MarkdownEditor } from "@/components/MarkdownEditor";
import "@/lib/i18n";

describe("MarkdownEditor", () => {
  it("renders the initial value in the textarea", () => {
    render(<MarkdownEditor value="# Hello" onChange={vi.fn()} />);
    expect(screen.getByRole("textbox")).toHaveValue("# Hello");
  });

  it("calls onChange when typing", async () => {
    const onChange = vi.fn();
    render(<MarkdownEditor value="" onChange={onChange} />);

    await userEvent.type(screen.getByRole("textbox"), "a");

    expect(onChange).toHaveBeenCalledWith("a");
  });

  it("disables the textarea when readOnly is true", () => {
    render(<MarkdownEditor value="locked" onChange={vi.fn()} readOnly />);
    expect(screen.getByRole("textbox")).toBeDisabled();
  });
});
