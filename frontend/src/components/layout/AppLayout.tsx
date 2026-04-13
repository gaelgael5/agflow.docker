import { useEffect, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { ChatWindow } from "@/components/ChatWindow";
import { Toaster } from "@/components/ui/sonner";
import { agentsApi, type AgentSummary } from "@/lib/agentsApi";

interface Props {
  children: ReactNode;
}

export function AppLayout({ children }: Props) {
  const location = useLocation();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [assistantOpen, setAssistantOpen] = useState(false);

  const assistantQuery = useQuery<AgentSummary | null>({
    queryKey: ["assistant-agent"],
    queryFn: () => agentsApi.getAssistant(),
    staleTime: 30_000,
  });
  const assistantAgent = assistantQuery.data ?? null;

  // Close the mobile drawer whenever the route changes.
  useEffect(() => {
    setSidebarOpen(false);
  }, [location.pathname]);

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* Desktop sidebar (always visible on md+) and mobile drawer */}
      <Sidebar
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />

      {/* Mobile-only backdrop shown when the drawer is open */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-30 bg-zinc-900/40 backdrop-blur-sm md:hidden"
          onClick={() => setSidebarOpen(false)}
          aria-hidden="true"
        />
      )}

      <div className="flex-1 flex flex-col min-w-0">
        <TopBar
          onOpenSidebar={() => setSidebarOpen(true)}
          onToggleAssistant={
            assistantAgent
              ? () => setAssistantOpen((v) => !v)
              : undefined
          }
          assistantActive={assistantOpen}
          assistantName={assistantAgent?.display_name}
        />
        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>

      {assistantOpen && assistantAgent && (
        <ChatWindow
          dockerfileId={assistantAgent.dockerfile_id}
          title={assistantAgent.display_name}
          onClose={() => setAssistantOpen(false)}
        />
      )}

      <Toaster />
    </div>
  );
}
