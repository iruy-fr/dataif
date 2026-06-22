import { useEffect, useState } from "react";

const EXPIRY_LEEWAY_SECONDS = 30;

function buildStorageKeys(storageKey) {
  return {
    sessionKey: `${storageKey}.session`,
  };
}

function normalizeTokens(payload) {
  const now = Math.floor(Date.now() / 1000);
  return {
    accessToken: payload.access_token,
    refreshToken: payload.refresh_token || "",
    idToken: payload.id_token || "",
    tokenType: payload.token_type || "Bearer",
    expiresAt: now + Number(payload.expires_in || 0),
    refreshExpiresAt: payload.refresh_expires_in ? now + Number(payload.refresh_expires_in) : 0,
  };
}

function readJsonStorage(key, storage) {
  const raw = storage.getItem(key);
  if (!raw) {
    return null;
  }

  try {
    return JSON.parse(raw);
  } catch (_error) {
    storage.removeItem(key);
    return null;
  }
}

function persistSession(keys, session) {
  window.localStorage.setItem(keys.sessionKey, JSON.stringify(session));
}

function readSession(keys) {
  return readJsonStorage(keys.sessionKey, window.localStorage);
}

function clearStoredState(keys) {
  window.localStorage.removeItem(keys.sessionKey);
}

function isExpired(expiresAt, leewaySeconds = EXPIRY_LEEWAY_SECONDS) {
  if (!expiresAt) {
    return true;
  }
  const now = Math.floor(Date.now() / 1000);
  return expiresAt <= now + leewaySeconds;
}

async function requestAuth(apiBaseUrl, path, payload) {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const detailText = await response.text();
    try {
      const detailPayload = JSON.parse(detailText);
      throw new Error(detailPayload.detail || `Falha HTTP ${response.status}`);
    } catch (_error) {
      throw new Error(detailText || `Falha HTTP ${response.status}`);
    }
  }

  return normalizeTokens(await response.json());
}

async function requestPasswordLogin(apiBaseUrl, username, password) {
  return requestAuth(apiBaseUrl, "/api/admin/login", {
    username,
    password,
  });
}

async function requestRefresh(apiBaseUrl, refreshToken) {
  return requestAuth(apiBaseUrl, "/api/admin/refresh", {
    refresh_token: refreshToken,
  });
}

async function validateAdminSession(apiBaseUrl, accessToken) {
  const response = await fetch(`${apiBaseUrl}/api/admin/whoami`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });

  if (!response.ok) {
    const detailText = await response.text();
    throw new Error(`Falha ao validar a sessão admin: ${response.status} - ${detailText}`);
  }

  const payload = await response.json();
  return payload.claims || {};
}

function buildAuthenticatedState(session, claims) {
  return {
    status: "authenticated",
    accessToken: session.accessToken,
    refreshToken: session.refreshToken,
    idToken: session.idToken,
    expiresAt: session.expiresAt,
    refreshExpiresAt: session.refreshExpiresAt,
    claims,
    error: "",
  };
}

function buildSignedOutState(error = "") {
  return {
    status: "signed_out",
    accessToken: "",
    refreshToken: "",
    idToken: "",
    expiresAt: 0,
    refreshExpiresAt: 0,
    claims: null,
    error,
  };
}

export function useAdminAuth({ apiBaseUrl, storageKey }) {
  const storageKeys = buildStorageKeys(storageKey);
  const [session, setSession] = useState({
    status: "loading",
    accessToken: "",
    refreshToken: "",
    idToken: "",
    expiresAt: 0,
    refreshExpiresAt: 0,
    claims: null,
    error: "",
  });

  async function applyValidatedSession(tokens) {
    const claims = await validateAdminSession(apiBaseUrl, tokens.accessToken);
    const nextSession = { ...tokens, claims };
    persistSession(storageKeys, nextSession);
    setSession(buildAuthenticatedState(tokens, claims));
    return nextSession;
  }

  async function getAccessToken() {
    const currentSession = readSession(storageKeys);
    if (!currentSession) {
      throw new Error("Autenticacao admin obrigatoria.");
    }

    if (!isExpired(currentSession.expiresAt)) {
      if (session.status !== "authenticated" && currentSession.claims) {
        setSession(buildAuthenticatedState(currentSession, currentSession.claims));
      }
      return currentSession.accessToken;
    }

    if (!currentSession.refreshToken || isExpired(currentSession.refreshExpiresAt, 0)) {
      clearStoredState(storageKeys);
      setSession(buildSignedOutState("Sessão expirada. Entre novamente."));
      throw new Error("Sessão admin expirada. Entre novamente.");
    }

    const refreshed = await requestRefresh(apiBaseUrl, currentSession.refreshToken);
    const nextSession = await applyValidatedSession(refreshed);
    return nextSession.accessToken;
  }

  async function login(username, password) {
    setSession((current) => ({ ...current, status: "loading", error: "" }));

    try {
      const tokens = await requestPasswordLogin(apiBaseUrl, username, password);
      await applyValidatedSession(tokens);
      return true;
    } catch (error) {
      clearStoredState(storageKeys);
      setSession(
        buildSignedOutState(error instanceof Error ? error.message : "Falha ao iniciar a sessão admin."),
      );
      return false;
    }
  }

  function logout() {
    clearStoredState(storageKeys);
    setSession(buildSignedOutState(""));
  }

  useEffect(() => {
    let active = true;

    async function bootstrap() {
      try {
        const storedSession = readSession(storageKeys);
        if (!storedSession) {
          if (active) {
            setSession(buildSignedOutState(""));
          }
          return;
        }

        if (isExpired(storedSession.expiresAt)) {
          if (!storedSession.refreshToken || isExpired(storedSession.refreshExpiresAt, 0)) {
            throw new Error("Sessão expirada. Entre novamente.");
          }

          const refreshed = await requestRefresh(apiBaseUrl, storedSession.refreshToken);
          await applyValidatedSession(refreshed);
          return;
        }

        await applyValidatedSession(storedSession);
      } catch (error) {
        clearStoredState(storageKeys);
        if (active) {
          setSession(
            buildSignedOutState(
              error instanceof Error ? error.message : "Falha ao carregar a sessão admin.",
            ),
          );
        }
      }
    }

    bootstrap();

    return () => {
      active = false;
    };
  }, []);

  return {
    ...session,
    login,
    logout,
    getAccessToken,
  };
}
