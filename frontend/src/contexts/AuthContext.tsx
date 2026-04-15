'use client';
import { createContext, useContext, useState, useEffect, ReactNode, useCallback } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { authLogin, authRegister, authMe, authLogout, AuthUser } from '@/lib/api';
import { getToken, setToken, clearToken } from '@/lib/auth';

// ── Types ─────────────────────────────────────────────────────────────────────

interface AuthContextType {
  user: AuthUser | null;
  isLoading: boolean;
  backendError: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, companyName: string) => Promise<void>;
  logout: () => Promise<void>;
}

// ── Context ───────────────────────────────────────────────────────────────────

const AuthContext = createContext<AuthContextType | null>(null);

const PUBLIC_PATHS = ['/', '/auth/login', '/auth/register'];

// ── Provider ──────────────────────────────────────────────────────────────────

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [backendError, setBackendError] = useState(false);
  const router = useRouter();
  const pathname = usePathname();

  // On mount: validate stored token
  useEffect(() => {
    const token = getToken();

    if (!token) {
      setIsLoading(false);
      if (!PUBLIC_PATHS.includes(pathname)) {
        router.replace('/auth/login');
      }
      return;
    }

    authMe()
      .then((userData) => {
        setUser(userData);
        setBackendError(false);
        // If on auth/landing page with valid session, go to dashboard
        if (PUBLIC_PATHS.includes(pathname)) {
          router.replace('/dashboard');
        }
      })
      .catch((err) => {
        // Network error (backend down) — don't clear token, show error
        if (!err?.response) {
          setBackendError(true);
          setIsLoading(false);
          return;
        }
        clearToken();
        if (!PUBLIC_PATHS.includes(pathname)) {
          router.replace('/auth/login');
        }
      })
      .finally(() => setIsLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const { access_token } = await authLogin(email, password);
    setToken(access_token);
    const userData = await authMe();
    setUser(userData);
    router.push('/dashboard');
  }, [router]);

  const register = useCallback(async (email: string, password: string, companyName: string) => {
    const { access_token } = await authRegister(email, password, companyName);
    setToken(access_token);
    const userData = await authMe();
    setUser(userData);
    router.push('/dashboard');
  }, [router]);

  const logout = useCallback(async () => {
    await authLogout();
    clearToken();
    setUser(null);
    router.push('/auth/login');
  }, [router]);

  return (
    <AuthContext.Provider value={{ user, isLoading, backendError, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useAuth(): AuthContextType {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within <AuthProvider>');
  return ctx;
}
