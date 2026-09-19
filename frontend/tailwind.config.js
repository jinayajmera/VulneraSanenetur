/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        retro: {
          bg: '#a8dcd1',
          panel: '#c0eae1',
          card: '#b0ded4',
          header: '#53c0aa',
          headerDark: '#3fa792',
          border: '#26685c',
          borderLight: '#479b8c',
          input: '#d5f3ec',
          text: '#0f332c',
          textMuted: '#2d685c',
          badge: '#99d4c7',
        },
        surgical: {
          dark: '#0f332c',
          card: '#c0eae1',
          cardHover: '#b2ded4',
          border: '#26685c',
          accent: '#19806f',
          success: '#108e68',
          warning: '#c27b0a',
          danger: '#c53030',
          muted: '#3b7569',
        }
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'Courier New', 'monospace'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
      }
    },
  },
  plugins: [],
}
