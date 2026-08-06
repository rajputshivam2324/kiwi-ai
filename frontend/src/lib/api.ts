/** Unified backend base URL — single port for builder, research, finance */
export const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

export async function authHeaders(getToken: () => Promise<string | null>) {
  const token = await getToken();
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}
