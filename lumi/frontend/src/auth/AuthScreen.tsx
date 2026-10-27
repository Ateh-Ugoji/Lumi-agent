import { useState, type FormEvent } from "react";
import { authErrorMessage } from "./errors";
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

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    if (!EMAIL_RE.test(email.trim())) {
      setError("Escribe un correo válido.");
      return;
    }
    if (mode === "register" && password.length < 8) {
      setError("La contraseña necesita al menos 8 caracteres.");
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
        <h1 className={styles.title}>{mode === "login" ? "Entra a Lumi" : "Crea tu cuenta"}</h1>
        {notice && !error && <p className={styles.notice}>{notice}</p>}
        {mode === "register" && (
          <label className={styles.field}>
            <span>Nombre</span>
            <input
              className={styles.input}
              value={name}
              autoComplete="name"
              onChange={(e) => setName(e.target.value)}
            />
          </label>
        )}
        <label className={styles.field}>
          <span>Correo</span>
          <input
            className={styles.input}
            type="email"
            value={email}
            autoComplete="email"
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <label className={styles.field}>
          <span>Contraseña</span>
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
          {busy ? "Un momento…" : mode === "login" ? "Entrar" : "Crear cuenta"}
        </button>
        <button type="button" className={styles.switch} onClick={switchMode}>
          {mode === "login" ? "No tengo cuenta" : "Ya tengo cuenta"}
        </button>
      </form>
    </main>
  );
}
