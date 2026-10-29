import { useState, type FormEvent } from "react";
import { authErrorMessage } from "./errors";
import { useT } from "../i18n/index.ts";
import LangToggle from "../i18n/LangToggle";
import styles from "./AuthScreen.module.css";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function AuthScreen({
  notice,
  onLogin,
  onRegister,
}: {
  notice?: string;
  onLogin: (email: string, password: string) => Promise<void>;
  onRegister: (email: string, password: string, name: string) => Promise<void>;
}) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const t = useT();

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    if (!EMAIL_RE.test(email.trim())) {
      setError(t("auth.invalid_email"));
      return;
    }
    if (mode === "register" && password.length < 8) {
      setError(t("auth.password_short"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") await onLogin(email.trim(), password);
      else await onRegister(email.trim(), password, name);
    } catch (err) {
      setError(authErrorMessage(err, mode));
      setBusy(false);
    }
  };

  const switchMode = () => {
    setMode(mode === "login" ? "register" : "login");
    setError(null);
  };

  return (
    <main className={styles.page}>
      <form className={styles.card} onSubmit={submit} noValidate>
        <LangToggle className={styles.lang} />
        <h1 className={styles.title}>
          {mode === "login" ? t("auth.title_signin") : t("auth.title_signup")}
        </h1>
        {notice && !error && <p className={styles.notice}>{notice}</p>}
        {mode === "register" && (
          <label className={styles.field}>
            <span>{t("auth.name")}</span>
            <input
              className={styles.input}
              value={name}
              autoComplete="name"
              onChange={(e) => setName(e.target.value)}
            />
          </label>
        )}
        <label className={styles.field}>
          <span>{t("auth.email")}</span>
          <input
            className={styles.input}
            type="email"
            value={email}
            autoComplete="email"
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <label className={styles.field}>
          <span>{t("auth.password")}</span>
          <input
            className={styles.input}
            type="password"
            value={password}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && (
          <p role="alert" className={styles.error}>
            {error}
          </p>
        )}
        <button type="submit" className={styles.submit} disabled={busy}>
          {busy ? t("auth.one_moment") : mode === "login" ? t("auth.signin") : t("auth.signup")}
        </button>
        <button type="button" className={styles.switch} onClick={switchMode}>
          {mode === "login" ? t("auth.no_account") : t("auth.have_account")}
        </button>
      </form>
    </main>
  );
}
