import { useCallback, useMemo, useState } from "react";

const STORAGE_KEY = "agflow_token";

export type AppRole = "admin" | "operator" | "viewer";

export interface UseAuth {
  token: string | null;
  isAuthenticated: boolean;
  role: AppRole;
  isAdmin: boolean;
  isOperator: boolean;
  setToken: (token: string) => void;
  logout: () => void;
}

function extractRole(token: string | null): AppRole {
  if (!token) return "viewer";
  try {
    const payload = JSON.parse(atob(token.split(".")[1] ?? ""));
    const role = payload.role as string | undefined;
    if (role === "admin" || role === "operator" || role === "viewer") return role;
    return "admin"; // backward compat: old tokens without role → admin
  } catch {
    return "viewer";
  }
}

export function useAuth(): UseAuth {
  const [token, setTokenState] = useState<string | null>(() =>
    localStorage.getItem(STORAGE_KEY),
  );

  const role = useMemo(() => extractRole(token), [token]);

  const setToken = useCallback((newToken: string) => {
    localStorage.setItem(STORAGE_KEY, newToken);
    setTokenState(newToken);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
    setTokenState(null);
  }, []);

  return {
    token,
    isAuthenticated: token !== null,
    role,
    isAdmin: role === "admin",
    isOperator: role === "admin" || role === "operator",
    setToken,
    logout,
  };
}
