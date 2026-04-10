import { useCallback, useState } from "react";

const STORAGE_KEY = "agflow_token";

export interface UseAuth {
  token: string | null;
  isAuthenticated: boolean;
  setToken: (token: string) => void;
  logout: () => void;
}

export function useAuth(): UseAuth {
  const [token, setTokenState] = useState<string | null>(() =>
    localStorage.getItem(STORAGE_KEY),
  );

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
    setToken,
    logout,
  };
}
