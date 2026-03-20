import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // Backgrounds
        "bg-base": "#0a0b0e",
        "bg-panel": "#0f1117",
        "bg-card": "#161a23",
        "bg-hover": "#1c2130",

        // Borders
        border: "#2a3045",

        // Text
        "text-primary": "#e2e8f0",
        "text-muted": "#94a3b8",
        "text-subtle": "#64748b",

        // Accent
        accent: "#3b82f6",

        // Alert levels
        critical: "#ef4444",
        high: "#f97316",
        medium: "#eab308",
        low: "#22c55e",
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Monaco", "Consolas", "monospace"],
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};

export default config;
