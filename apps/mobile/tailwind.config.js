// Cream + crimson, same values as the web app (apps/web/src/app/globals.css); activity and alert colors come
// from src/shared/tokens.json, the shared design tokens.
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./App.tsx", "./src/**/*.{ts,tsx}"],
  presets: [require("nativewind/preset")],
  theme: {
    extend: {
      colors: {
        background: { DEFAULT: "#f5efe3", dark: "#1c1416" },
        foreground: { DEFAULT: "#1c1416", dark: "#f5efe3" },
        card: { DEFAULT: "#fbf8f1", dark: "#251b1d" },
        muted: { DEFAULT: "#ece4d4", dark: "#2f2427", foreground: "#5c4f4a", "foreground-dark": "#c9bba9" },
        border: { DEFAULT: "#ddd2bf", dark: "#3d2f32" },
        primary: { DEFAULT: "#9b1c31", dark: "#e8667a", foreground: "#f5efe3", "foreground-dark": "#1c1416" },
      },
      borderRadius: { xl: "1.25rem" },
    },
  },
};
