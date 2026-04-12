import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { VaultProvider } from "./hooks/useVault";
import App from "./App";
import "./index.css";
import "./lib/i18n";

const queryClient = new QueryClient();

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
