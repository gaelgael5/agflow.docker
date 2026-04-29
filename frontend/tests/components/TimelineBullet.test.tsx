import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { TimelineBullet } from "@/components/timeline/TimelineBullet";

describe("TimelineBullet", () => {
  it("rend un bullet par défaut", () => {
    const { container } = render(<TimelineBullet />);
    const bullet = container.querySelector("[data-timeline-bullet]");
    expect(bullet).toBeTruthy();
    expect(bullet?.getAttribute("data-variant")).toBe("default");
  });

  it("applique la variante selected", () => {
    const { container } = render(<TimelineBullet variant="selected" />);
    expect(
      container.querySelector('[data-timeline-bullet][data-variant="selected"]'),
    ).toBeTruthy();
  });

  it("applique la variante live", () => {
    const { container } = render(<TimelineBullet variant="live" />);
    const bullet = container.querySelector(
      '[data-timeline-bullet][data-variant="live"]',
    );
    expect(bullet).toBeTruthy();
  });

  it("applique la variante muted", () => {
    const { container } = render(<TimelineBullet variant="muted" />);
    expect(
      container.querySelector('[data-timeline-bullet][data-variant="muted"]'),
    ).toBeTruthy();
  });

  it("respecte la taille personnalisée", () => {
    const { container } = render(<TimelineBullet size={16} />);
    const bullet = container.querySelector<HTMLElement>("[data-timeline-bullet]");
    expect(bullet?.style.width).toBe("16px");
    expect(bullet?.style.height).toBe("16px");
  });
});
