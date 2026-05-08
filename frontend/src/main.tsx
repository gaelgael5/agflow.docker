import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { VaultProvider } from "./hooks/useVault";
import App from "./App";
import "./index.css";
import "./lib/i18n";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Ne jamais retenter les erreurs 4xx (auth, forbidden, not found)
      retry: (failureCount, error) => {
        const status = (error as { response?: { status?: number } })?.response?.status;
        if (status !== undefined && status >= 400 && status < 500) return false;
        return failureCount < 2;
      },
      // Stopper le polling dès qu'une query est en erreur
      refetchIntervalInBackground: false,
    },
  },
});

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Root element #root not found");
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <VaultProvider>
          <App />
        </VaultProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
