/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        pit: { 50: '#fff7ed', 500: '#f97316', 900: '#431407' },
      },
    },
  },
  plugins: [],
}
