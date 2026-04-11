import { Routes, Route, Navigate } from "react-router-dom";
import { LoginPage } from "./pages/LoginPage";
import { HomePage } from "./pages/HomePage";
import { SecretsPage } from "./pages/SecretsPage";
import { RolesPage } from "./pages/RolesPage";
import { DockerfilesPage } from "./pages/DockerfilesPage";
import { DiscoveryServicesPage } from "./pages/DiscoveryServicesPage";
import { MCPCatalogPage } from "./pages/MCPCatalogPage";
import { SkillsCatalogPage } from "./pages/SkillsCatalogPage";
import { AgentsPage } from "./pages/AgentsPage";
import { AgentEditorPage } from "./pages/AgentEditorPage";
import { ProtectedRoute } from "./components/ProtectedRoute";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <HomePage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/secrets"
        element={
          <ProtectedRoute>
            <SecretsPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/roles"
        element={
          <ProtectedRoute>
            <RolesPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/dockerfiles"
        element={
          <ProtectedRoute>
            <DockerfilesPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/discovery-services"
        element={
          <ProtectedRoute>
            <DiscoveryServicesPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/mcp-catalog"
        element={
          <ProtectedRoute>
            <MCPCatalogPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/skills-catalog"
        element={
          <ProtectedRoute>
            <SkillsCatalogPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/agents"
        element={
          <ProtectedRoute>
            <AgentsPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/agents/new"
        element={
          <ProtectedRoute>
            <AgentEditorPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/agents/:id"
        element={
          <ProtectedRoute>
            <AgentEditorPage />
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
