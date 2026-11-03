// Same calm palette as the web app (apps/web/src/app/globals.css); activity and alert colors come
// from src/shared/tokens.json, the shared design tokens.
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./App.tsx", "./src/**/*.{ts,tsx}"],
  presets: [require("nativewind/preset")],
  theme: {
    extend: {
      colors: {
        background: { DEFAULT: "#f6fbfa", dark: "#141b24" },
        foreground: { DEFAULT: "#2b3442", dark: "#e6ecf2" },
        card: { DEFAULT: "#ffffff", dark: "#1b2430" },
        muted: { DEFAULT: "#eef4f4", dark: "#232d3a", foreground: "#66717f", "foreground-dark": "#a9b4c2" },
        border: { DEFAULT: "#dde7e7", dark: "#2e3a48" },
        primary: { DEFAULT: "#3f9a8e", dark: "#6cc6b8" },
      },
      borderRadius: { xl: "1.25rem" },
    },
  },
};
