import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useAuth } from "@/hooks/useAuth";

describe("useAuth", () => {
  it("starts unauthenticated when no token in storage", () => {
    const { result } = renderHook(() => useAuth());
    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.token).toBe(null);
  });

  it("becomes authenticated after setToken", () => {
    const { result } = renderHook(() => useAuth());
    act(() => {
      result.current.setToken("fake.jwt.token");
    });
    expect(result.current.isAuthenticated).toBe(true);
    expect(result.current.token).toBe("fake.jwt.token");
    expect(localStorage.getItem("agflow_token")).toBe("fake.jwt.token");
  });

  it("clears auth on logout", () => {
    localStorage.setItem("agflow_token", "pre.existing.token");
    const { result } = renderHook(() => useAuth());
    expect(result.current.isAuthenticated).toBe(true);
    act(() => {
      result.current.logout();
    });
    expect(result.current.isAuthenticated).toBe(false);
    expect(localStorage.getItem("agflow_token")).toBe(null);
  });
});
