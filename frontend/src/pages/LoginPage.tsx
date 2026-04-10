import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";

export function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { setToken } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const res = await api.post<{ access_token: string }>(
        "/admin/auth/login",
        { email, password },
      );
      setToken(res.data.access_token);
      navigate("/");
    } catch {
      setError(t("login.error_invalid"));
    }
  }

  return (
    <div style={{ maxWidth: 360, margin: "4rem auto", padding: "1rem" }}>
      <h1>{t("login.title")}</h1>
      <form onSubmit={handleSubmit}>
        <div>
          <label>
            {t("login.email")}
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </label>
        </div>
        <div>
          <label>
            {t("login.password")}
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
        </div>
        {error && (
          <p role="alert" style={{ color: "red" }}>
            {error}
          </p>
        )}
        <button type="submit">{t("login.submit")}</button>
      </form>
    </div>
  );
}
