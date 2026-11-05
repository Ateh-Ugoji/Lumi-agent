import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3010,
    // Answer on both localhost and 127.0.0.1 (and other hostnames on the LAN).
    host: true,
  },
});
