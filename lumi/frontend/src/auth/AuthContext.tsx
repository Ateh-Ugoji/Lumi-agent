import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  currentToken,
  fetchMe,
  login as apiLogin,
  logout as apiLogout,
  onUnauthorized,
  register as apiRegister,
  type User,
} from "../api";
import { clearLocalSession } from "../session";
import AuthScreen from "./AuthScreen";

type AuthValue = {
  user: User;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthValue | null>(null);

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthGate>");
  return value;
}

type State = { status: "checking" } | { status: "anonymous"; notice?: string } | { status: "in"; user: User };

/** Shows the login screen until there is a valid token; then renders the app. */
export default function AuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>(() =>
    currentToken() ? { status: "checking" } : { status: "anonymous" },
  );

  useEffect(() => {
    return onUnauthorized(() => {
      clearLocalSession();
      setState({ status: "anonymous", notice: "Tu sesión terminó. Entra otra vez." });
    });
  }, []);

  useEffect(() => {
    if (state.status !== "checking") return;
    let cancelled = false;
    fetchMe()
      .then((user) => !cancelled && setState({ status: "in", user }))
      .catch(() => !cancelled && setState((s) => (s.status === "checking" ? { status: "anonymous" } : s)));
    return () => {
      cancelled = true;
    };
  }, [state.status]);

  const logout = useCallback(async () => {
    await apiLogout();
    clearLocalSession();
    setState({ status: "anonymous" });
  }, []);

  const value = useMemo<AuthValue | null>(
    () => (state.status === "in" ? { user: state.user, logout } : null),
    [state, logout],
  );

  if (state.status === "checking") {
    return <div role="status" aria-label="Cargando" style={{ minHeight: "100vh" }} />;
  }
  if (state.status === "anonymous" || !value) {
    return (
      <AuthScreen
        notice={state.status === "anonymous" ? state.notice : undefined}
        onLogin={async (email, password) => {
          const user = await apiLogin(email, password);
          setState({ status: "in", user });
        }}
        onRegister={async (email, password, name) => {
          const user = await apiRegister(email, password, name);
          setState({ status: "in", user });
        }}
      />
    );
  }
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
