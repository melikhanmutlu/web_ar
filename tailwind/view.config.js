// Tailwind config for templates/view.html. Mirrors its former inline
// `tailwind.config` (a different palette than base.html).
module.exports = {
  darkMode: 'class',
  content: [
    './templates/view.html',
    './templates/_*.html',
    './static/js/viewer/**/*.js',
    './static/viewer.js',
  ],
  theme: {
    extend: {
      colors: {
        primary: '#4CAF50',
        secondary: '#2196F3',
        success: '#4CAF50',
        error: '#f44336',
      },
    },
  },
};
