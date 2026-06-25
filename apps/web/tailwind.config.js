/** @type {import('tailwindcss').Config} */
const defaultTheme = require('tailwindcss/defaultTheme');

module.exports = {
  content: [
    './src/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        display: ['var(--font-syne)', 'Syne', ...defaultTheme.fontFamily.sans],
        sans: ['var(--font-manrope)', 'Manrope', ...defaultTheme.fontFamily.sans],
        mono: ['var(--font-dm-mono)', 'DM Mono', ...defaultTheme.fontFamily.mono],
      },
      colors: {
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))',
        },
        secondary: {
          DEFAULT: 'hsl(var(--secondary))',
          foreground: 'hsl(var(--secondary-foreground))',
        },
        destructive: {
          DEFAULT: 'hsl(var(--destructive))',
          foreground: 'hsl(var(--destructive-foreground))',
        },
        success: {
          DEFAULT: 'hsl(var(--success))',
          foreground: 'hsl(var(--success-foreground))',
        },
        warning: {
          DEFAULT: 'hsl(var(--warning))',
          foreground: 'hsl(var(--warning-foreground))',
        },
        info: {
          DEFAULT: 'hsl(var(--info))',
          foreground: 'hsl(var(--info-foreground))',
        },
        muted: {
          DEFAULT: 'hsl(var(--muted))',
          foreground: 'hsl(var(--muted-foreground))',
        },
        accent: {
          DEFAULT: 'hsl(var(--accent))',
          foreground: 'hsl(var(--accent-foreground))',
        },
        popover: {
          DEFAULT: 'hsl(var(--popover))',
          foreground: 'hsl(var(--popover-foreground))',
        },
        card: {
          DEFAULT: 'hsl(var(--card))',
          foreground: 'hsl(var(--card-foreground))',
        },
        gold: {
          DEFAULT: '#B8860B',
          50: '#FDF8E8',
          100: '#F9EDBE',
          500: '#B8860B',
          600: '#9A7209',
          700: '#7C5D07',
        },
        warm: {
          50: '#FAF8F5',
          100: '#F3F0EB',
          200: '#E6E2DB',
          300: '#D4CFC6',
          400: '#A09890',
          500: '#6B6560',
          600: '#4A4540',
          700: '#2A2724',
          800: '#1A1714',
        },
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
      },
      boxShadow: {
        'card': '0 1px 3px rgba(26,23,20,.04), 0 1px 2px rgba(26,23,20,.03)',
        'card-hover': '0 4px 16px rgba(26,23,20,.06), 0 1px 4px rgba(26,23,20,.04)',
        'card-lg': '0 12px 40px rgba(26,23,20,.08), 0 4px 12px rgba(26,23,20,.04)',
        'sidebar': '2px 0 12px rgba(26,23,20,.04)',
      },
      keyframes: {
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(16px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'fade-in': {
          '0%': { opacity: '0', transform: 'translateY(6px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'slide-in': {
          '0%': { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(0)' },
        },
      },
      animation: {
        'fade-up': 'fade-up 0.5s cubic-bezier(.4,0,.2,1) forwards',
        'fade-in': 'fade-in 0.35s cubic-bezier(.4,0,.2,1) forwards',
        'slide-in': 'slide-in 0.3s cubic-bezier(.4,0,.2,1)',
      },
    },
  },
  plugins: [],
}
