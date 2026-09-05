import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#eef4ff",
          500: "#2563eb",
          700: "#1d4ed8",
          900: "#1e3a8a",
        },
      },
    },
  },
  plugins: [],
};
export default config;