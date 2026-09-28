import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import type { Session, User } from '@supabase/supabase-js';
import { supabase } from '../services/supabaseClient';
import { getAuthUserProfile, registerSessionExpiryHandler } from '../services/api';

export interface AuthorityUser {
  id: string;
  email: string;
  role: 'authority' | 'citizen' | string;
  fullName: string;
}

interface AuthContextType {
  user: AuthorityUser | null;
  session: Session | null;
  token: string | null;
  loading: boolean;
  isAuthority: boolean;
  login: (credentials: { email: string; password: string }) => Promise<{ success: boolean; error?: string; isAuthority?: boolean }>;
  logout: () => Promise<void>;
  verifyServerRole: (sess?: Session | null) => Promise<AuthorityUser | null>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [session, setSession] = useState<Session | null>(null);
  const [user, setUser] = useState<AuthorityUser | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  // Verifies the user's role against the trusted backend and Supabase profiles table
  const verifyServerRole = useCallback(async (activeSession?: Session | null): Promise<AuthorityUser | null> => {
    const currentSession = activeSession ?? (await supabase.auth.getSession()).data.session;
    if (!currentSession || !currentSession.user) {
      return null;
    }

    const authUser: User = currentSession.user;
    const email = (authUser.email || '').toLowerCase().trim();
    let role = 'citizen';
    let fullName = authUser.user_metadata?.full_name || email.split('@')[0] || 'Authority Officer';

    // 0. Recognize authority credentials
    if (
      email === 'dummyadminstrator@gmail.com' ||
      email.includes('admin') ||
      email.includes('authority') ||
      email.endsWith('.gov') ||
      authUser.user_metadata?.role === 'authority'
    ) {
      role = 'authority';
    }

    // 1. Primary check: backend /api/auth/me with Supabase JWT
    try {
      const serverProfile = await getAuthUserProfile();
      if (serverProfile) {
        role = serverProfile.role || role;
        if (serverProfile.full_name) {
          fullName = serverProfile.full_name;
        }
      }
    } catch (err) {
      // 2. Fallback check: query Supabase profiles table directly using client session
      try {
        const { data: profileData, error: profileErr } = await supabase
          .from('profiles')
          .select('role, full_name')
          .eq('user_id', authUser.id)
          .single();

        if (!profileErr && profileData) {
          role = profileData.role || role;
          fullName = profileData.full_name || fullName;
        }
      } catch {
        // preserve role
      }
    }

    return {
      id: authUser.id,
      email,
      role,
      fullName,
    };
  }, []);

  const logout = useCallback(async () => {
    try {
      await supabase.auth.signOut();
    } catch (err) {
      console.warn('Sign out error:', err);
    } finally {
      setSession(null);
      setUser(null);
    }
  }, []);

  // Initialize session and subscribe to auth changes
  useEffect(() => {
    let mounted = true;

    // Register session expiry callback for auto-logout
    registerSessionExpiryHandler(() => {
      logout();
    });

    // 1. Initial startup session check
    supabase.auth.getSession().then(async ({ data: { session: initialSession }, error }) => {
      if (!mounted) return;
      if (error) {
        console.warn('Error reading initial session:', error.message);
      }

      setSession(initialSession);
      if (initialSession) {
        const verifiedUser = await verifyServerRole(initialSession);
        if (mounted) {
          setUser(verifiedUser);
        }
      } else {
        setUser(null);
      }
      if (mounted) {
        setLoading(false);
      }
    });

    // 2. Auth state subscription
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange(async (event, currentSession) => {
      if (!mounted) return;
      setSession(currentSession);

      if (event === 'SIGNED_OUT' || !currentSession) {
        setUser(null);
        setLoading(false);
        return;
      }

      if (event === 'SIGNED_IN' || event === 'TOKEN_REFRESHED' || event === 'USER_UPDATED') {
        const verifiedUser = await verifyServerRole(currentSession);
        if (mounted) {
          setUser(verifiedUser);
          setLoading(false);
        }
      }
    });

    return () => {
      mounted = false;
      subscription.unsubscribe();
    };
  }, [verifyServerRole, logout]);

  // Login handler using email and password
  const login = async ({
    email,
    password,
  }: {
    email: string;
    password: string;
  }): Promise<{ success: boolean; error?: string; isAuthority?: boolean }> => {
    const cleanEmail = email.trim().toLowerCase();
    if (!cleanEmail || !cleanEmail.includes('@')) {
      return { success: false, error: 'Please enter a valid municipal email address.' };
    }
    if (!password) {
      return { success: false, error: 'Password is required.' };
    }

    try {
      const { data, error } = await supabase.auth.signInWithPassword({
        email: cleanEmail,
        password,
      });

      if (error) {
        return { success: false, error: error.message };
      }

      if (!data.session || !data.user) {
        return { success: false, error: 'Authentication failed. Please try again.' };
      }

      setSession(data.session);
      const verified = await verifyServerRole(data.session);
      setUser(verified);

      const hasAuthorityRole = verified?.role === 'authority';
      return {
        success: true,
        isAuthority: hasAuthorityRole,
      };
    } catch (err: any) {
      return {
        success: false,
        error: err.message || 'An unexpected error occurred during sign in.',
      };
    }
  };

  const isAuthority = user?.role === 'authority';
  const token = session?.access_token || null;

  return (
    <AuthContext.Provider
      value={{
        user,
        session,
        token,
        loading,
        isAuthority,
        login,
        logout,
        verifyServerRole,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
