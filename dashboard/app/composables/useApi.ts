import type { AuthResponse, User } from '~/types'

export function useApi() {
  const config = useRuntimeConfig()
  const token = useState<string>('auth-token', () => '')
  const user = useState<User | null>('auth-user', () => null)

  function hydrate() {
    if (!import.meta.client || token.value) return
    token.value = localStorage.getItem('smartbox_token') || ''
    const raw = localStorage.getItem('smartbox_user')
    if (raw) {
      try { user.value = JSON.parse(raw) as User } catch { logout() }
    }
  }

  function setAuth(auth: AuthResponse) {
    token.value = auth.access_token
    user.value = auth.user
    if (import.meta.client) {
      localStorage.setItem('smartbox_token', auth.access_token)
      localStorage.setItem('smartbox_user', JSON.stringify(auth.user))
    }
  }

  function logout() {
    token.value = ''
    user.value = null
    if (import.meta.client) {
      localStorage.removeItem('smartbox_token')
      localStorage.removeItem('smartbox_user')
    }
  }

  async function api<T>(path: string, options: Record<string, unknown> = {}) {
    return await $fetch<T>(path, {
      baseURL: config.public.apiBaseUrl as string,
      ...options,
      headers: {
        ...(token.value ? { Authorization: `Bearer ${token.value}` } : {}),
        ...((options.headers as Record<string, string> | undefined) || {}),
      },
    })
  }

  return { api, hydrate, logout, setAuth, token, user }
}
