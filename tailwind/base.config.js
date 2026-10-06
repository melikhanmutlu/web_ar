// Tailwind config for pages that extend templates/base.html (auth, pricing,
// profile, billing, discover, ...). Mirrors the inline `tailwind.config` the
// Play CDN used to read at runtime.
module.exports = {
  darkMode: 'class',
  content: [
    './templates/**/*.html',
    './static/js/**/*.js',
    '!./static/js/**/*.min.js',
    '!./static/js/meshopt_decoder.js',
  ],
  theme: {
    extend: {
      colors: {
        primary: '#1F2937',
        'primary-dark': '#111827',
        secondary: '#4B5563',
        'secondary-dark': '#374151',
        cyan: {
          400: '#00E5FF',
          500: '#00B2CC',
          600: '#008FA3',
        },
        orange: {
          500: '#FF3D00',
          600: '#C30000',
        },
      },
      fontFamily: {
        poppins: ['Poppins', 'sans-serif'],
        inter: ['Inter', 'sans-serif'],
      },
    },
  },
};
