import { useEffect, useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Boxes, LogIn, Shield } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { setToken } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [authMode, setAuthMode] = useState<"keycloak" | "local" | null>(null);
  const [showLocalForm, setShowLocalForm] = useState(false);

  // Handle token from callback redirect
  useEffect(() => {
    const token = searchParams.get("token");
    if (token) {
      setToken(token);
      navigate("/", { replace: true });
    }
    const err = searchParams.get("error");
    if (err === "account_disabled") {
      setError(t("login.error_disabled"));
    }
  }, [searchParams, setToken, navigate, t]);

  // Fetch auth mode
  useEffect(() => {
    api.get<{ mode: string }>("/admin/auth/mode")
      .then((res) => setAuthMode(res.data.mode as "keycloak" | "local"))
      .catch(() => setAuthMode("local"));
  }, []);

  async function handleLocalSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await api.post<{ access_token: string }>(
        "/admin/auth/login",
        { email, password },
      );
      setToken(res.data.access_token);
      navigate("/");
    } catch {
      setError(t("login.error_invalid"));
    } finally {
      setLoading(false);
    }
  }

  function handleKeycloakLogin() {
    window.location.href = "/api/admin/auth/oidc/login";
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center px-4 py-8">
      <Card className="w-full max-w-sm">
        <CardHeader className="items-center text-center">
          <div className="w-10 h-10 rounded-lg bg-primary flex items-center justify-center shadow-sm mb-2">
            <Boxes className="w-5 h-5 text-primary-foreground" />
          </div>
          <CardTitle>{t("login.title")}</CardTitle>
          <CardDescription>agflow.docker</CardDescription>
        </CardHeader>

        <CardContent className="flex flex-col gap-4">
          {/* Keycloak SSO button (shown when auth_mode=keycloak or while loading) */}
          {authMode !== "local" && (
            <Button
              type="button"
              className="w-full"
              onClick={handleKeycloakLogin}
              disabled={authMode === null}
            >
              <Shield className="w-4 h-4 mr-2" />
              {t("login.sso")}
            </Button>
          )}

          {/* Local login form */}
          {(authMode === "local" || showLocalForm) && (
            <>
              {authMode === "keycloak" && (
                <div className="relative">
                  <div className="absolute inset-0 flex items-center">
                    <span className="w-full border-t" />
                  </div>
                  <div className="relative flex justify-center text-xs uppercase">
                    <span className="bg-card px-2 text-muted-foreground">
                      {t("login.or")}
                    </span>
                  </div>
                </div>
              )}
              <form onSubmit={handleLocalSubmit} className="flex flex-col gap-4">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="login-email">{t("login.email")}</Label>
                  <Input
                    id="login-email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    autoComplete="email"
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="login-password">{t("login.password")}</Label>
                  <Input
                    id="login-password"
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    autoComplete="current-password"
                  />
                </div>
                {error && (
                  <p role="alert" className="text-[12px] text-destructive">
                    {error}
                  </p>
                )}
                <Button type="submit" variant={authMode === "keycloak" ? "outline" : "default"} className="w-full" disabled={loading}>
                  <LogIn className="w-4 h-4 mr-2" />
                  {t("login.submit")}
                </Button>
              </form>
            </>
          )}

          {/* Link to show local form when in keycloak mode */}
          {authMode === "keycloak" && !showLocalForm && (
            <button
              type="button"
              className="text-[11px] text-muted-foreground hover:text-foreground transition-colors"
              onClick={() => setShowLocalForm(true)}
            >
              {t("login.local_fallback")}
            </button>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
