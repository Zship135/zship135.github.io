const { fontFamily } = require('tailwindcss/defaultTheme')

module.exports = {
  theme: {
    extend: {
      fontFamily: {
        rockwell: ['Rockwell', 'Rokkitt', 'Slab Serif', 'Times New Roman', ...fontFamily.serif]
      }
    }
  }
}