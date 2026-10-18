// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  compatibilityDate: '2025-07-15',
  ssr: false,
  devtools: { enabled: false },
  css: ['~/assets/css/main.css'],
  // Nuxt emits runtime-config.js with a stable filename. Keep production
  // config out of browsers' old /_nuxt/ immutable cache by versioning the
  // asset directory; Vercel also gives this file an explicit no-store header.
  app: {
    buildAssetsDir: '/_smartbox-v2/',
  },
  runtimeConfig: {
    public: {
      apiBaseUrl: process.env.NUXT_PUBLIC_API_BASE_URL
        || (process.env.NODE_ENV === 'production'
          ? 'https://api.smartbox.id.vn'
          : 'http://localhost:8000'),
    },
  },
  nitro: { preset: 'static' },
})
