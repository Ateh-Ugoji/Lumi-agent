import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import AuthGate from "./auth/AuthContext";
import "./styles/global.css";
import "./styles/theme.css";
import "./styles/animations.css";
import { applyStoredLightMode } from "./hooks/useLightMode";

applyStoredLightMode(); // light/white by default, before first paint

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AuthGate>
      <App />
    </AuthGate>
  </StrictMode>,
);
