/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx,ts,tsx}"],
  theme: {
    extend: {},
  },
  plugins: [],
  // The Ledger component defines its own colour tokens (bone, ink, stone, etc.)
  // via a <style> block and plain CSS classes, so Tailwind only needs to supply
  // layout/spacing utilities here — no custom theme colours required.
};
