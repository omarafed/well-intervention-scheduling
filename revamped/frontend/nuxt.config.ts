export default defineNuxtConfig({
  compatibilityDate: '2025-05-15',
  ssr: false,
  devtools: { enabled: false },
  modules: ['@pinia/nuxt', '@nuxtjs/tailwindcss'],
  css: ['~/assets/main.css'],
  runtimeConfig: { public: { apiBase: 'http://localhost:8080/api' } },
  app: { head: { title: 'Bayu · Platform Scheduling', meta: [{ name: 'description', content: 'Plan well interventions, optimize platform schedules, and explore uncertainty.' }] } },
})
