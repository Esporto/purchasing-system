// tailwind-config.js - theme for the Tailwind CDN (must load right after the CDN script)
    tailwind.config = {
theme: {
  extend: {
    fontFamily: {
      sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
      mono: ['JetBrains Mono', 'monospace'],
    },
    screens: {
      'xs': '420px',
      '2xl': '1440px',
      '3xl': '1700px'
    },
    colors: {
      brand: {
        50: '#f0f7ff',
        100: '#e0effe',
        500: '#0284c7',
        600: '#0369a1',
        700: '#075985',
        800: '#0c4a6e',
        900: '#082f49',
      }
    }
  }
}
    }
