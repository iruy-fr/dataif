import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { useAdminAuth } from "./adminAuth";
import AppHeader from "./components/AppHeader";
import { cx } from "./utils/cx";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";
const METABASE_URL = import.meta.env.VITE_METABASE_URL || "/metabase/";
const AIRFLOW_URL = import.meta.env.VITE_AIRFLOW_URL || "/airflow/";
const GITHUB_REPO_URL = import.meta.env.VITE_GITHUB_REPO_URL || "https://github.com/iruy-fr/dataif";

const NAV_ITEMS = [
  { path: "/", label: "Início" },
  { path: "/pipelines", label: "Pipelines" },
  { path: "/conexoes", label: "Conexões" },
  { path: "/dashboards", label: "Dashboards" },
  { path: "/sql", label: "SQL" },
];
const AUTH_REQUIRED_NAV_PATHS = new Set(["/pipelines", "/conexoes", "/dashboards", "/sql"]);

const ADMIN_NAV_ITEMS = [
  { path: "/admin", label: "Workspace" },
  { path: "/admin/airflow", label: "Airflow" },
  { path: "/admin/metabase", label: "Metabase" },
  { path: "/admin/sgbd", label: "SGBD" },
];

const LOGIN_ROUTE = "/login";
const SETTINGS_ROUTE = "/configurações";
const ADMIN_SETTINGS_ROUTE = "/admin/configurações";
const CONNECTIONS_ROUTE = "/conexoes";
const CONNECTION_CREATE_ROUTE = "/conexoes/nova";
const CONNECTION_DETAIL_ROUTE = "/conexoes/detalhes";
const PIPELINE_CREATE_ROUTE = "/pipelines/nova";
const RETURN_ROUTE_KEY = "dataif.admin.returnRoute";

const ROUTE_PATHS = new Set([
  LOGIN_ROUTE,
  SETTINGS_ROUTE,
  ADMIN_SETTINGS_ROUTE,
  CONNECTIONS_ROUTE,
  CONNECTION_CREATE_ROUTE,
  CONNECTION_DETAIL_ROUTE,
  PIPELINE_CREATE_ROUTE,
  ...NAV_ITEMS.map((item) => item.path),
  ...ADMIN_NAV_ITEMS.map((item) => item.path),
]);

const INITIAL_CONNECTION_FORM = {
  connection_name: "",
  is_active: true,
};

const INITIAL_PIPELINE_FORM = {
  pipeline_name: "",
  connection_key: "",
  schedule: "0 3 * * *",
  selected_years: [],
  selected_microdados_types: [],
  is_active: true,
};

const INITIAL_ADMIN_LLM_FORM = {
  provider: "ollama",
  ollama: {
    base_url: "http://ollama:11434",
    model: "sabia-7b",
  },
  maritaca: {
    api_url: "https://chat.maritaca.ai/api/chat/completions",
    model: "sabia-4",
    timeout_seconds: 60,
    api_key: "",
    clear_api_key: false,
    has_api_key: false,
    masked_api_key: "",
  },
};

const INITIAL_ADMIN_USER_FORM = {
  username: "",
  email: "",
  first_name: "",
  last_name: "",
  password: "",
  enabled: true,
};

function getRouteFromHash() {
  const raw = window.location.hash.replace(/^#/, "") || "/";
  return ROUTE_PATHS.has(raw) ? raw : "/";
}

function navigate(path) {
  window.location.hash = path;
}

function storeReturnRoute(path) {
  const safePath = path && path !== LOGIN_ROUTE ? path : "/pipelines";
  window.sessionStorage.setItem(RETURN_ROUTE_KEY, safePath);
}

function consumeReturnRoute() {
  const path = window.sessionStorage.getItem(RETURN_ROUTE_KEY) || "/pipelines";
  window.sessionStorage.removeItem(RETURN_ROUTE_KEY);
  return path;
}

function isAdminRoute(path) {
  return path === "/admin" || path.startsWith("/admin/");
}

function formatTimestamp(value) {
  if (!value) {
    return "-";
  }

  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("pt-BR");
}

function formatStatus(status) {
  if (!status) {
    return "nao iniciado";
  }

  return String(status).replaceAll("_", " ");
}

function statusTone(status) {
  if (["success", "ready", "raw_loaded", "validated"].includes(status)) {
    return "success";
  }
  if (["failed", "error"].includes(status)) {
    return "danger";
  }
  if (["running", "queued", "pending", "not_started"].includes(status)) {
    return "warning";
  }
  return "neutral";
}

function buildHeaders(token, hasJsonBody = true) {
  return {
    Authorization: `Bearer ${token}`,
    ...(hasJsonBody ? { "Content-Type": "application/json" } : {}),
  };
}

function ButtonLink({ href, children, secondary = false }) {
  return (
    <a
      className={`button-link${secondary ? " secondary" : ""}`}
      href={href}
      target={href.startsWith("http") ? "_blank" : undefined}
      rel={href.startsWith("http") ? "noreferrer" : undefined}
    >
      {children}
    </a>
  );
}

function PageHeader({ title, actions, children }) {
  return (
    <div className="page-header">
      <div className="page-header-copy">
        <h1>{title}</h1>
        {children ? <p>{children}</p> : null}
      </div>
      {actions ? <div className="actions-row">{actions}</div> : null}
    </div>
  );
}

function Panel({ title, action, className, children }) {
  return (
    <article className={cx("panel", className)}>
      {title || action ? (
        <div className="panel-header">
          {title ? <h2>{title}</h2> : <span />}
          {action ? <div className="actions-row">{action}</div> : null}
        </div>
      ) : null}
      {children}
    </article>
  );
}

function StatusBadge({ status }) {
  return <span className={`status-badge ${statusTone(status)}`}>{formatStatus(status)}</span>;
}

function SummaryGrid({ items, className }) {
  return (
    <dl className={cx("summary-grid", className)}>
      {items.map((item) => (
        <div key={item.label} className="summary-item">
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function RunsTable({ runs, emptyMessage }) {
  return (
    <div className="table-shell">
      <table>
        <thead>
          <tr>
            <th>DAG</th>
            <th>Status</th>
            <th>Início</th>
            <th>Fim</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={`${run.dag_id}-${run.dag_run_id}`}>
              <td>
                <strong>{run.dag_id}</strong>
                <span>{run.dag_run_id}</span>
              </td>
              <td>
                <StatusBadge status={run.state} />
              </td>
              <td>{formatTimestamp(run.start_date || run.logical_date)}</td>
              <td>{formatTimestamp(run.end_date)}</td>
            </tr>
          ))}
          {runs.length === 0 ? (
            <tr>
              <td colSpan="4">{emptyMessage}</td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}

function SqlResultsTable({ result, emptyMessage = "Nenhum resultado." }) {
  if (!result) {
    return null;
  }

  if (!result.rows.length) {
    return (
      <div className="empty-state compact-empty-state">
        <p>{emptyMessage}</p>
      </div>
    );
  }

  return (
    <div className="table-shell">
      <table>
        <thead>
          <tr>
            {result.fields.map((field) => (
              <th key={field.name}>{field.name}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.map((row, rowIndex) => (
            <tr key={`row-${rowIndex}`}>
              {result.fields.map((field) => (
                <td key={`${rowIndex}-${field.name}`}>{formatSqlCell(row[field.name])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function formatSqlCell(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }

  if (typeof value === "object") {
    return JSON.stringify(value);
  }

  return String(value);
}

function serializeSelection(value) {
  if (!Array.isArray(value) || value.length === 0) {
    return "";
  }

  return value.join(", ");
}

function AdminGate({ auth, message, onLoginRequest }) {
  return (
    <section className="page">
      <PageHeader title="Area restrita">{message}</PageHeader>
      <Panel>
        <div className="empty-state">
          <p>{message}</p>
          <div className="actions-row">
            <button type="button" onClick={onLoginRequest} disabled={auth.status === "loading"}>
              {auth.status === "loading" ? "Verificando..." : "Login"}
            </button>
          </div>
        </div>
      </Panel>
    </section>
  );
}

function LoginPage({ auth, onSubmit, onBack }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  async function handleSubmit(event) {
    event.preventDefault();
    await onSubmit(username, password);
  }

  if (auth.status === "authenticated") {
    return (
      <section className="page">
        <PageHeader title="Sessão ativa">O acesso administrativo ja esta liberado.</PageHeader>
        <Panel>
          <div className="actions-row">
            <button type="button" onClick={onBack}>
              Continuar
            </button>
          </div>
        </Panel>
      </section>
    );
  }

  return (
    <section className="page narrow-page">
      <PageHeader title="Login">Acesso administrativo local.</PageHeader>
      <Panel>
        <form className="form-grid" onSubmit={handleSubmit}>
          <label className="field">
            <span>Usuario</span>
            <input
              type="text"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              placeholder="dataif-admin"
              autoComplete="username"
              required
            />
          </label>

          <label className="field">
            <span>Senha</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="********"
              autoComplete="current-password"
              required
            />
          </label>

          <div className="actions-row">
            <button type="submit" disabled={auth.status === "loading"}>
              {auth.status === "loading" ? "Entrando..." : "Entrar"}
            </button>
            <button type="button" className="secondary" onClick={onBack}>
              Voltar
            </button>
          </div>
        </form>
      </Panel>
    </section>
  );
}

function SettingsPage({ auth, onLoginRequest, onLogout }) {
  if (auth.status !== "authenticated") {
    return (
      <AdminGate
        auth={auth}
        message="As configurações exigem sessão autenticada."
        onLoginRequest={onLoginRequest}
      />
    );
  }

  const accountLabel = auth.claims?.preferred_username || auth.claims?.email || "Administrador";

  return (
    <section className="page">
      <PageHeader
        title="Conta"
        actions={
          <>
            <button type="button" className="secondary" onClick={() => navigate("/admin")}>
              Workspace
            </button>
            <button type="button" onClick={onLogout}>
              Sair
            </button>
          </>
        }
      />
      <Panel>
        <SummaryGrid
          items={[
            { label: "Usuario", value: accountLabel },
            { label: "Status", value: "Sessão ativa" },
            { label: "Escopo", value: "Workspace administrativo" },
          ]}
        />
      </Panel>
    </section>
  );
}

function normalizeAdminLlmForm(payload) {
  const config = payload?.config || {};
  const ollama = config.ollama || {};
  const maritaca = config.maritaca || {};
  return {
    provider: config.provider || "ollama",
    ollama: {
      base_url: ollama.base_url || INITIAL_ADMIN_LLM_FORM.ollama.base_url,
      model: ollama.model || INITIAL_ADMIN_LLM_FORM.ollama.model,
    },
    maritaca: {
      api_url: maritaca.api_url || INITIAL_ADMIN_LLM_FORM.maritaca.api_url,
      model: maritaca.model || INITIAL_ADMIN_LLM_FORM.maritaca.model,
      timeout_seconds: maritaca.timeout_seconds || INITIAL_ADMIN_LLM_FORM.maritaca.timeout_seconds,
      api_key: "",
      clear_api_key: false,
      has_api_key: Boolean(maritaca.has_api_key),
      api_key_scope: maritaca.api_key_scope || "empty",
      has_personal_api_key: Boolean(maritaca.has_personal_api_key),
      masked_api_key: maritaca.masked_api_key || "",
    },
  };
}

function AdminSettingsPage({ auth, onLoginRequest, adminRequest }) {
  const [llmForm, setLlmForm] = useState(INITIAL_ADMIN_LLM_FORM);
  const [llmStatus, setLlmStatus] = useState(null);
  const [users, setUsers] = useState([]);
  const [userForm, setUserForm] = useState(INITIAL_ADMIN_USER_FORM);
  const [isLoading, setIsLoading] = useState(true);
  const [isSavingLlm, setIsSavingLlm] = useState(false);
  const [isCreatingUser, setIsCreatingUser] = useState(false);
  const [deletingUserId, setDeletingUserId] = useState("");
  const [syncingUserId, setSyncingUserId] = useState("");
  const [localNotice, setLocalNotice] = useState("");
  const [localError, setLocalError] = useState("");

  async function loadAdminSettings() {
    setIsLoading(true);
    setLocalError("");
    try {
      const [llmResponse, userResponse] = await Promise.all([
        adminRequest("/api/admin/settings/llm"),
        adminRequest("/api/admin/users"),
      ]);
      setLlmForm(normalizeAdminLlmForm(llmResponse));
      setLlmStatus(llmResponse.status || null);
      setUsers(userResponse.items || []);
    } catch (requestError) {
      setLocalError(requestError instanceof Error ? requestError.message : "Falha ao carregar as configurações administrativas.");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    if (auth.status !== "authenticated") {
      return;
    }
    loadAdminSettings();
  }, [auth.status]);

  if (auth.status !== "authenticated") {
    return (
      <AdminGate
        auth={auth}
        message="A configuração administrativa exige sessão autenticada."
        onLoginRequest={onLoginRequest}
      />
    );
  }

  async function handleSaveLlmSettings(event) {
    event.preventDefault();
    setIsSavingLlm(true);
    setLocalError("");
    setLocalNotice("");
    try {
      const response = await adminRequest("/api/admin/settings/llm", {
        method: "PATCH",
        body: {
          provider: llmForm.provider,
          ollama: llmForm.ollama,
          maritaca: {
            api_url: llmForm.maritaca.api_url,
            model: llmForm.maritaca.model,
            timeout_seconds: Number(llmForm.maritaca.timeout_seconds) || 60,
            api_key: llmForm.maritaca.api_key || undefined,
            clear_api_key: llmForm.maritaca.clear_api_key,
          },
        },
      });
      setLlmForm(normalizeAdminLlmForm(response));
      setLlmStatus(response.status || null);
      setLocalNotice("Configuração de LLM atualizada.");
    } catch (requestError) {
      setLocalError(requestError instanceof Error ? requestError.message : "Falha ao salvar a configuração de LLM.");
    } finally {
      setIsSavingLlm(false);
    }
  }

  async function handleCreateUser(event) {
    event.preventDefault();
    setIsCreatingUser(true);
    setLocalError("");
    setLocalNotice("");
    try {
      const response = await adminRequest("/api/admin/users", {
        method: "POST",
        body: userForm,
      });
      setUsers((current) => [...current, response.user].sort((left, right) => left.username.localeCompare(right.username)));
      setUserForm(INITIAL_ADMIN_USER_FORM);
      setLocalNotice(`Usuario admin ${response.user.username} criado no Keycloak e no Metabase.`);
    } catch (requestError) {
      setLocalError(requestError instanceof Error ? requestError.message : "Falha ao criar usuario admin.");
    } finally {
      setIsCreatingUser(false);
    }
  }

  async function handleDeleteUser(userId, username) {
    if (!userId || !window.confirm(`Excluir o usuario admin ${username}?`)) {
      return;
    }

    setDeletingUserId(userId);
    setLocalError("");
    setLocalNotice("");
    try {
      await adminRequest(`/api/admin/users/${userId}`, { method: "DELETE" });
      setUsers((current) => current.filter((item) => item.id !== userId));
      setLocalNotice(`Usuario admin ${username} removido do Keycloak e desativado no Metabase.`);
    } catch (requestError) {
      setLocalError(requestError instanceof Error ? requestError.message : "Falha ao remover usuario admin.");
    } finally {
      setDeletingUserId("");
    }
  }

  async function handleSyncMetabaseUser(userId, username) {
    const password = window.prompt(`Senha inicial do Metabase para ${username}`);
    if (!userId || !password) {
      return;
    }

    setSyncingUserId(userId);
    setLocalError("");
    setLocalNotice("");
    try {
      const response = await adminRequest(`/api/admin/users/${userId}/metabase-sync`, {
        method: "POST",
        body: { password },
      });
      setUsers((current) =>
        current
          .map((item) => (item.id === userId ? response.user : item))
          .sort((left, right) => left.username.localeCompare(right.username)),
      );
      setLocalNotice(`Usuario admin ${username} sincronizado no Metabase.`);
    } catch (requestError) {
      setLocalError(requestError instanceof Error ? requestError.message : "Falha ao sincronizar usuario no Metabase.");
    } finally {
      setSyncingUserId("");
    }
  }

  return (
    <section className="page">
      <PageHeader title="Configurações do Administrador">Persistência de LLM e gestão de admins do Keycloak.</PageHeader>

      {localNotice ? <p className="notice-banner">{localNotice}</p> : null}
      {localError ? <p className="error-banner">{localError}</p> : null}

      <Panel title="Resumo atual">
        <SummaryGrid
          items={[
            { label: "Provider", value: llmForm.provider },
            { label: "Status", value: llmStatus?.available ? "disponível" : "indisponível" },
            { label: "Admins", value: String(users.length) },
            { label: "Chave Maritaca", value: llmForm.maritaca.api_key_scope === "personal" ? "própria" : llmForm.maritaca.has_api_key ? "global" : "vazia" },
          ]}
        />
      </Panel>

      <div className="card-grid two-col">
        <Panel title="Provider de LLM">
          {isLoading ? (
            <p className="muted">Carregando configurações...</p>
          ) : (
            <form className="stack" onSubmit={handleSaveLlmSettings}>
              <div className="form-grid two-col-form">
                <label className="field">
                  <span>Provider ativo</span>
                  <select
                    value={llmForm.provider}
                    onChange={(event) => setLlmForm((current) => ({ ...current, provider: event.target.value }))}
                  >
                    <option value="ollama">Ollama</option>
                    <option value="maritaca">Maritaca</option>
                  </select>
                </label>
              </div>

              {llmForm.provider === "ollama" ? (
                <div className="form-grid two-col-form">
                  <label className="field">
                    <span>Base URL do Ollama</span>
                    <input
                      type="text"
                      value={llmForm.ollama.base_url}
                      onChange={(event) =>
                        setLlmForm((current) => ({
                          ...current,
                          ollama: { ...current.ollama, base_url: event.target.value },
                        }))
                      }
                      required
                    />
                  </label>
                  <label className="field">
                    <span>Modelo do Ollama</span>
                    <input
                      type="text"
                      value={llmForm.ollama.model}
                      onChange={(event) =>
                        setLlmForm((current) => ({
                          ...current,
                          ollama: { ...current.ollama, model: event.target.value },
                        }))
                      }
                      required
                    />
                  </label>
                </div>
              ) : (
                <div className="form-grid two-col-form">
                  <label className="field">
                    <span>URL da API Maritaca</span>
                    <input
                      type="text"
                      value={llmForm.maritaca.api_url}
                      onChange={(event) =>
                        setLlmForm((current) => ({
                          ...current,
                          maritaca: { ...current.maritaca, api_url: event.target.value },
                        }))
                      }
                      required
                    />
                  </label>
                  <label className="field">
                    <span>Modelo da Maritaca</span>
                    <input
                      type="text"
                      value={llmForm.maritaca.model}
                      onChange={(event) =>
                        setLlmForm((current) => ({
                          ...current,
                          maritaca: { ...current.maritaca, model: event.target.value },
                        }))
                      }
                      required
                    />
                  </label>
                  <label className="field">
                    <span>Timeout (segundos)</span>
                    <input
                      type="number"
                      min="1"
                      max="300"
                      value={llmForm.maritaca.timeout_seconds}
                      onChange={(event) =>
                        setLlmForm((current) => ({
                          ...current,
                          maritaca: { ...current.maritaca, timeout_seconds: event.target.value },
                        }))
                      }
                      required
                    />
                  </label>
                  <label className="field">
                    <span>Minha chave da Maritaca</span>
                    <input
                      type="password"
                      value={llmForm.maritaca.api_key}
                      onChange={(event) =>
                        setLlmForm((current) => ({
                          ...current,
                          maritaca: { ...current.maritaca, api_key: event.target.value, clear_api_key: false },
                        }))
                      }
                      placeholder={llmForm.maritaca.masked_api_key || "Nao alterar"}
                    />
                  </label>
                </div>
              )}

              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={llmForm.maritaca.clear_api_key}
                  onChange={(event) =>
                    setLlmForm((current) => ({
                      ...current,
                      maritaca: {
                        ...current.maritaca,
                        clear_api_key: event.target.checked,
                        api_key: event.target.checked ? "" : current.maritaca.api_key,
                      },
                    }))
                  }
                />
                <span>Limpar minha chave salva da Maritaca</span>
              </label>

              <div className="actions-row">
                <button type="submit" disabled={isSavingLlm}>
                  {isSavingLlm ? "Salvando..." : "Salvar configuração"}
                </button>
              </div>
            </form>
          )}
        </Panel>

        <Panel title="Status do provider">
          <div className="subsection">
            <SummaryGrid
              items={[
                { label: "Provider verificado", value: llmStatus?.provider || llmForm.provider },
                { label: "Disponivel", value: llmStatus?.available ? "sim" : "nao" },
              ]}
            />
            <p className="muted">{llmStatus?.detail || "Sem validação recente."}</p>
          </div>
        </Panel>
      </div>

      <div className="card-grid two-col">
        <Panel title="Criar admin">
          <form className="stack" onSubmit={handleCreateUser}>
            <div className="form-grid two-col-form">
              <label className="field">
                <span>Usuario</span>
                <input
                  type="text"
                  value={userForm.username}
                  onChange={(event) => setUserForm((current) => ({ ...current, username: event.target.value }))}
                  required
                />
              </label>
              <label className="field">
                <span>Email</span>
                <input
                  type="email"
                  value={userForm.email}
                  onChange={(event) => setUserForm((current) => ({ ...current, email: event.target.value }))}
                  required
                />
              </label>
              <label className="field">
                <span>Primeiro nome</span>
                <input
                  type="text"
                  value={userForm.first_name}
                  onChange={(event) => setUserForm((current) => ({ ...current, first_name: event.target.value }))}
                />
              </label>
              <label className="field">
                <span>Sobrenome</span>
                <input
                  type="text"
                  value={userForm.last_name}
                  onChange={(event) => setUserForm((current) => ({ ...current, last_name: event.target.value }))}
                />
              </label>
              <label className="field">
                <span>Senha inicial</span>
                <input
                  type="password"
                  value={userForm.password}
                  onChange={(event) => setUserForm((current) => ({ ...current, password: event.target.value }))}
                  required
                />
              </label>
            </div>

            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={userForm.enabled}
                onChange={(event) => setUserForm((current) => ({ ...current, enabled: event.target.checked }))}
              />
              <span>Usuario habilitado</span>
            </label>

            <div className="actions-row">
              <button type="submit" disabled={isCreatingUser}>
                {isCreatingUser ? "Criando..." : "Criar admin"}
              </button>
            </div>
          </form>
        </Panel>

        <Panel title="Admins atuais">
          {isLoading ? (
            <p className="muted">Carregando usuarios...</p>
          ) : users.length === 0 ? (
            <div className="empty-state compact-empty-state">
              <p>Nenhum admin encontrado.</p>
            </div>
          ) : (
            <div className="record-list">
              {users.map((user) => (
                <div key={user.id} className="record-row">
                  <div>
                    <strong>{user.username}</strong>
                    <span>{user.email || "sem email"}</span>
                  </div>
                  <div className="record-actions">
                    <span className={`status-badge ${user.metabase_synced ? "success" : "warning"}`}>
                      {user.metabase_synced ? "metabase ok" : "metabase pendente"}
                    </span>
                    <span className={`status-badge ${user.enabled ? "success" : "danger"}`}>
                      {user.enabled ? "ativo" : "inativo"}
                    </span>
                    <button
                      type="button"
                      className="secondary"
                      disabled={deletingUserId === user.id}
                      onClick={() => handleDeleteUser(user.id, user.username)}
                    >
                      {deletingUserId === user.id ? "Excluindo..." : "Excluir"}
                    </button>
                    {!user.metabase_synced ? (
                      <button
                        type="button"
                        className="secondary"
                        disabled={syncingUserId === user.id}
                        onClick={() => handleSyncMetabaseUser(user.id, user.username)}
                      >
                        {syncingUserId === user.id ? "Sincronizando..." : "Sincronizar"}
                      </button>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>
    </section>
  );
}

function AdminWorkspacePage({ auth, route, onLoginRequest, onLogout }) {
  if (auth.status !== "authenticated") {
    return (
      <AdminGate
        auth={auth}
        message="O workspace administrativo exige sessão admin."
        onLoginRequest={onLoginRequest}
      />
    );
  }

  if (route === "/admin/airflow") {
    return (
      <section className="page">
        <PageHeader title="Airflow" actions={<ButtonLink href={AIRFLOW_URL}>Abrir Airflow</ButtonLink>} />
        <Panel>
          <SummaryGrid
            items={[
              { label: "Uso", value: "Orquestração" },
              { label: "Acesso", value: "Externo" },
              { label: "Sessão", value: "Admin" },
            ]}
          />
        </Panel>
      </section>
    );
  }

  if (route === "/admin/metabase") {
    return (
      <section className="page">
        <PageHeader title="Metabase" actions={<ButtonLink href={METABASE_URL}>Abrir Metabase</ButtonLink>} />
        <Panel>
          <SummaryGrid
            items={[
              { label: "Uso", value: "Dashboards" },
              { label: "Acesso", value: "Externo" },
              { label: "Sessão", value: "Admin" },
            ]}
          />
        </Panel>
      </section>
    );
  }

  if (route === "/admin/sgbd") {
    return (
      <section className="page">
        <PageHeader
          title="SGBD"
          actions={
            <>
              <button type="button" className="secondary" onClick={() => navigate("/sql")}>
                Abrir SQL
              </button>
              <button type="button" onClick={onLogout}>
                Encerrar sessão
              </button>
            </>
          }
        />
        <Panel>
          <SummaryGrid
            items={[
              { label: "Uso", value: "Consulta e manutenção" },
              { label: "Acesso", value: "Interno" },
              { label: "Sessão", value: "Admin" },
            ]}
          />
        </Panel>
      </section>
    );
  }

  return (
    <section className="page">
      <PageHeader title="Workspace admin" />
      <div className="card-grid three-col">
        <Panel
          title="Airflow"
          action={
            <button type="button" onClick={() => navigate("/admin/airflow")}>
              Abrir
            </button>
          }
        >
          <p className="muted">Orquestração.</p>
        </Panel>

        <Panel
          title="Metabase"
          action={
            <button type="button" onClick={() => navigate("/admin/metabase")}>
              Abrir
            </button>
          }
        >
          <p className="muted">Dashboards.</p>
        </Panel>

        <Panel
          title="SGBD"
          action={
            <button type="button" onClick={() => navigate("/admin/sgbd")}>
              Abrir
            </button>
          }
        >
          <p className="muted">SQL.</p>
        </Panel>
      </div>
    </section>
  );
}

function HomePage({ dashboardUrl, vannaQuestion, setVannaQuestion, vannaResult, vannaState, vannaError, onAskVanna }) {
  const resultRows = vannaResult?.rows || [];
  const resultColumns = resultRows.length > 0 ? Object.keys(resultRows[0]) : [];

  return (
    <section className="page">
      <PageHeader title="Início" />
      <div className="layout-main">
        <Panel title="Dados da Plataforma Nilo Peçanha" className="embed-panel">
          {dashboardUrl ? (
            <iframe title="metabase-dashboard-home" src={dashboardUrl} className="dashboard-frame" />
          ) : (
            <div className="empty-state">
              <p>Carregando dashboard.</p>
            </div>
          )}
        </Panel>

        <div className="stack">
          <Panel title="Vanna">
            <form className="vanna-form" onSubmit={onAskVanna}>
              <label className="field">
                <span>Pergunta</span>
                <input
                  type="text"
                  value={vannaQuestion}
                  onChange={(event) => setVannaQuestion(event.target.value)}
                  placeholder="Ex.: Qual a quantidade de matrículas no IFRS por ano?"
                  minLength={3}
                  maxLength={1000}
                />
              </label>
              <button type="submit" disabled={vannaState === "loading" || vannaQuestion.trim().length < 3}>
                {vannaState === "loading" ? "Consultando..." : "Perguntar"}
              </button>
            </form>

            {vannaError ? <p className="error-inline">{vannaError}</p> : null}

            {vannaResult ? (
              <div className="answer-block">
                <div className="answer-section">
                  <span className="muted">{vannaResult.row_count} registro(s)</span>
                  <pre>{vannaResult.sql}</pre>
                </div>

                {resultRows.length > 0 ? (
                  <div className="table-shell">
                    <table>
                      <thead>
                        <tr>
                          {resultColumns.map((column) => (
                            <th key={column}>{column}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {resultRows.map((row, index) => (
                          <tr key={`${index}-${JSON.stringify(row)}`}>
                            {resultColumns.map((column) => (
                              <td key={column}>{row[column] === null ? "-" : String(row[column])}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="muted">Sem registros para a pergunta.</p>
                )}
              </div>
            ) : null}
          </Panel>
        </div>
      </div>
    </section>
  );
}

function PipelinesPage({
  auth,
  route,
  onLoginRequest,
  pipelines,
  connections,
  selectedPipelineKey,
  onSelectPipeline,
  diagnosticsOverview,
  timelineOverview,
  dagRuns,
  pipelineAction,
  deleteAction,
  onTriggerOperation,
  onDeletePipeline,
  pipelineForm,
  setPipelineForm,
  createState,
  onSubmitPipeline,
  connectorDefinition,
}) {
  if (auth.status !== "authenticated") {
    return (
      <AdminGate
        auth={auth}
        message="As pipelines exigem sessão admin."
        onLoginRequest={onLoginRequest}
      />
    );
  }

  const selectedDiagnostics =
    diagnosticsOverview?.instance?.instance_key === selectedPipelineKey ? diagnosticsOverview : null;
  const selectedTimeline =
    timelineOverview?.instance?.instance_key === selectedPipelineKey ? timelineOverview : null;
  const selectedPipeline = pipelines.find((instance) => instance.instance_key === selectedPipelineKey) || null;
  const catalog = connectorDefinition?.selection_catalog || {};
  const availableYears = catalog.available_years || [];
  const availableTypes =
    pipelineForm.selected_years.length === 0
      ? []
      : (catalog.available_microdados_types || []).filter((type) =>
          pipelineForm.selected_years.every((year) => (catalog.types_by_year?.[year] || []).includes(type)),
        );

  function toggleYear(year) {
    const nextYears = pipelineForm.selected_years.includes(year)
      ? pipelineForm.selected_years.filter((item) => item !== year)
      : [...pipelineForm.selected_years, year];
    const nextTypes = pipelineForm.selected_microdados_types.filter((type) =>
      nextYears.every((selectedYear) => (catalog.types_by_year?.[selectedYear] || []).includes(type)),
    );
    setPipelineForm({ ...pipelineForm, selected_years: nextYears, selected_microdados_types: nextTypes });
  }

  function toggleType(type) {
    const nextTypes = pipelineForm.selected_microdados_types.includes(type)
      ? pipelineForm.selected_microdados_types.filter((item) => item !== type)
      : [...pipelineForm.selected_microdados_types, type];
    setPipelineForm({ ...pipelineForm, selected_microdados_types: nextTypes });
  }

  if (route === PIPELINE_CREATE_ROUTE) {
    return (
      <section className="page">
        <PageHeader
          title="Nova pipeline"
          actions={
            <button type="button" className="secondary" onClick={() => navigate("/pipelines")}>
              Voltar
            </button>
          }
        />

        <form className="stack" onSubmit={onSubmitPipeline}>
          <Panel title="Pipeline">
            <div className="form-grid two-col-form">
              <label className="field">
                <span>Nome</span>
                <input
                  type="text"
                  value={pipelineForm.pipeline_name}
                  onChange={(event) => setPipelineForm({ ...pipelineForm, pipeline_name: event.target.value })}
                  placeholder="Ex.: PNP Matriculas 2024"
                  required
                />
              </label>

              <label className="field">
                <span>conexão</span>
                <select
                  value={pipelineForm.connection_key}
                  onChange={(event) => setPipelineForm({ ...pipelineForm, connection_key: event.target.value })}
                  required
                >
                  <option value="">Selecione</option>
                  {connections.map((connection) => (
                    <option key={connection.connection_key} value={connection.connection_key}>
                      {connection.connection_name}
                    </option>
                  ))}
                </select>
              </label>

              <label className="field">
                <span>Cron</span>
                <input
                  type="text"
                  value={pipelineForm.schedule}
                  onChange={(event) => setPipelineForm({ ...pipelineForm, schedule: event.target.value })}
                  placeholder="0 3 * * *"
                />
              </label>
            </div>

            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={pipelineForm.is_active}
                onChange={(event) => setPipelineForm({ ...pipelineForm, is_active: event.target.checked })}
              />
              <span>Ativar apos criar</span>
            </label>
          </Panel>

          <div className="card-grid two-col">
            <Panel title="Anos">
              <div className="choice-list">
                {availableYears.map((year) => (
                  <label key={year} className="choice-item">
                    <input type="checkbox" checked={pipelineForm.selected_years.includes(year)} onChange={() => toggleYear(year)} />
                    <span>{year}</span>
                  </label>
                ))}
              </div>
            </Panel>

            <Panel title="Tipos">
              <div className="choice-list">
                {availableTypes.map((type) => (
                  <label key={type} className="choice-item">
                    <input
                      type="checkbox"
                      checked={pipelineForm.selected_microdados_types.includes(type)}
                      onChange={() => toggleType(type)}
                    />
                    <span>{type}</span>
                  </label>
                ))}
                {pipelineForm.selected_years.length === 0 ? <p className="muted">Selecione pelo menos um ano.</p> : null}
              </div>
            </Panel>
          </div>

          <div className="actions-row">
            <button type="submit" disabled={createState === "loading" || connections.length === 0}>
              {createState === "loading" ? "Criando..." : "Criar pipeline"}
            </button>
          </div>
        </form>
      </section>
    );
  }

  return (
    <section className="page">
      <PageHeader
        title="Pipelines"
        actions={
          <button type="button" onClick={() => navigate(PIPELINE_CREATE_ROUTE)}>
            Nova pipeline
          </button>
        }
      />

      <div className="layout-sidebar">
        <Panel title="Pipelines">
          <div className="selection-list">
            {pipelines.map((instance) => {
              const isSelected = selectedPipelineKey === instance.instance_key;
              const status = isSelected ? selectedTimeline?.ingestion?.status || "pending" : "pending";

              return (
                <button
                  key={instance.instance_key}
                  type="button"
                  className={`selection-item${isSelected ? " selected" : ""}`}
                  onClick={() => onSelectPipeline(instance.instance_key)}
                >
                  <div className="selection-item-head">
                    <strong>{instance.instance_name}</strong>
                    <StatusBadge status={status} />
                  </div>
                  <div className="selection-item-body">
                    <span>{instance.connection_name || instance.connection_key}</span>
                    <span>{serializeSelection(instance.selected_years) || "Sem anos"}</span>
                    <span>{serializeSelection(instance.selected_microdados_types) || "Sem tipos"}</span>
                    <span>{instance.schedule || "-"}</span>
                  </div>
                </button>
              );
            })}

            {pipelines.length === 0 ? <p className="muted">Nenhuma pipeline cadastrada.</p> : null}
          </div>
        </Panel>

        <div className="stack">
          <Panel
            title={selectedPipeline ? selectedPipeline.instance_name : "Operacao"}
            action={
              selectedPipeline ? (
                <>
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => onTriggerOperation("validate-sources")}
                    disabled={pipelineAction === "validate-sources"}
                  >
                    {pipelineAction === "validate-sources" ? "Validando..." : "Validar"}
                  </button>
                  <button
                    type="button"
                    onClick={() => onTriggerOperation("full-sync")}
                    disabled={pipelineAction === "full-sync"}
                  >
                    {pipelineAction === "full-sync" ? "Executando..." : "Executar"}
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => onDeletePipeline(selectedPipeline.instance_key)}
                    disabled={deleteAction === selectedPipeline.instance_key}
                  >
                    {deleteAction === selectedPipeline.instance_key ? "Excluindo..." : "Excluir pipeline"}
                  </button>
                </>
              ) : null
            }
          >
            {selectedPipeline ? (
              <div className="stack">
                <SummaryGrid
                  items={[
                    { label: "conexão", value: selectedPipeline.connection_name || selectedPipeline.connection_key },
                    { label: "Status", value: formatStatus(selectedTimeline?.ingestion?.status) },
                    { label: "Anos", value: serializeSelection(selectedPipeline.selected_years) || "-" },
                    { label: "Tipos", value: serializeSelection(selectedPipeline.selected_microdados_types) || "-" },
                    { label: "Cron", value: selectedPipeline.schedule || "-" },
                  ]}
                />

                <div className="card-grid two-col">
                  <div className="subsection">
                    <h3>Diagnóstico</h3>
                    <div className="record-list">
                      {(selectedDiagnostics?.diagnostics || []).map((item) => (
                        <div key={item.endpoint_key} className="record-row">
                          <div>
                            <strong>{item.source_label || item.endpoint_key}</strong>
                            <span>{item.operational_stage}</span>
                          </div>
                          <StatusBadge status={item.operational_status} />
                        </div>
                      ))}
                      {(selectedDiagnostics?.diagnostics || []).length === 0 ? <p className="muted">Sem diagnóstico.</p> : null}
                    </div>
                  </div>

                  <div className="subsection">
                    <h3>Timeline</h3>
                    <div className="record-list">
                      {(selectedTimeline?.run_events || []).map((event) => (
                        <div key={`${event.stage}-${event.run_id}`} className="record-row">
                          <div>
                            <strong>{event.stage_label}</strong>
                            <span>{formatTimestamp(event.timestamp)}</span>
                          </div>
                          <StatusBadge status={event.state} />
                        </div>
                      ))}
                      {(selectedTimeline?.run_events || []).length === 0 ? <p className="muted">Sem eventos.</p> : null}
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className="empty-state">
                <p>Selecione uma pipeline.</p>
              </div>
            )}
          </Panel>

          <Panel title="DAG runs">
            <RunsTable
              runs={selectedPipeline ? dagRuns : []}
              emptyMessage={selectedPipeline ? "Nenhuma execução recente." : "Selecione uma pipeline."}
            />
          </Panel>
        </div>
      </div>
    </section>
  );
}

function ConnectionsPage({
  auth,
  route,
  onLoginRequest,
  connectionForm,
  setConnectionForm,
  createState,
  onSubmitConnection,
  connections,
  selectedConnectionKey,
  detail,
  onOpenConnection,
  onOpenPipeline,
  deleteAction,
  onDeleteConnection,
}) {
  if (auth.status !== "authenticated") {
    return (
      <AdminGate
        auth={auth}
        message="A gestao de conexoes exige sessão admin."
        onLoginRequest={onLoginRequest}
      />
    );
  }

  const selectedConnection = connections.find((item) => item.connection_key === selectedConnectionKey) || detail?.connection || null;
  const linkedPipelines = detail?.pipelines || [];

  if (route === CONNECTION_CREATE_ROUTE) {
    return (
      <section className="page">
        <PageHeader
          title="Nova conexão"
          actions={
            <button type="button" className="secondary" onClick={() => navigate(CONNECTIONS_ROUTE)}>
              Voltar
            </button>
          }
        />

        <form className="stack" onSubmit={onSubmitConnection}>
          <Panel title="conexão">
            <label className="field">
              <span>Nome</span>
              <input
                type="text"
                value={connectionForm.connection_name}
                onChange={(event) => setConnectionForm({ ...connectionForm, connection_name: event.target.value })}
                placeholder="Ex.: PNP Principal"
                required
              />
            </label>

            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={connectionForm.is_active}
                onChange={(event) => setConnectionForm({ ...connectionForm, is_active: event.target.checked })}
              />
              <span>Ativar apos criar</span>
            </label>
          </Panel>

          <div className="actions-row">
            <button type="submit" disabled={createState === "loading"}>
              {createState === "loading" ? "Criando..." : "Criar conexão"}
            </button>
          </div>
        </form>
      </section>
    );
  }

  if (route === CONNECTION_DETAIL_ROUTE) {
    return (
      <section className="page">
        <PageHeader
          title={selectedConnection?.connection_name || "conexão"}
          actions={
            <>
              <button type="button" className="secondary" onClick={() => navigate(CONNECTIONS_ROUTE)}>
                Voltar
              </button>
              {selectedConnection ? (
                <button
                  type="button"
                  className="secondary"
                  onClick={() => onDeleteConnection(selectedConnection.connection_key)}
                  disabled={deleteAction === selectedConnection.connection_key}
                >
                  {deleteAction === selectedConnection.connection_key ? "Excluindo..." : "Excluir conexão"}
                </button>
              ) : null}
              <button
                type="button"
                onClick={() => {
                  window.sessionStorage.setItem("dataif.connection.selected", selectedConnection?.connection_key || "");
                  navigate(PIPELINE_CREATE_ROUTE);
                }}
              >
                Nova pipeline
              </button>
            </>
          }
        />

        {selectedConnection ? (
          <div className="stack">
            <Panel title="Resumo">
              <SummaryGrid
                items={[
                  { label: "Chave", value: selectedConnection.connection_key },
                  { label: "Status", value: selectedConnection.is_active ? "Ativa" : "Inativa" },
                  { label: "Validação", value: formatStatus(selectedConnection.validation_status) },
                  { label: "Pipelines", value: selectedConnection.pipeline_count || linkedPipelines.length },
                  { label: "Atualizado", value: formatTimestamp(selectedConnection.updated_at) },
                ]}
              />
            </Panel>

            <Panel title="Validação">
              <div className="record-row">
                <div>
                  <strong>{selectedConnection.validation_message}</strong>
                  <span>{selectedConnection.page_url || "-"}</span>
                </div>
                <StatusBadge status={selectedConnection.validation_status} />
              </div>
            </Panel>

            <Panel title="Pipelines vinculadas">
              <div className="record-list">
                {linkedPipelines.map((pipeline) => (
                  <button
                    key={pipeline.instance_key}
                    type="button"
                    className="selection-item"
                    onClick={() => onOpenPipeline(pipeline.instance_key)}
                  >
                    <div className="selection-item-head">
                      <strong>{pipeline.instance_name}</strong>
                      <StatusBadge status={pipeline.is_active ? "ready" : "pending"} />
                    </div>
                    <div className="selection-item-body">
                      <span>{serializeSelection(pipeline.selected_years) || "Sem anos"}</span>
                      <span>{serializeSelection(pipeline.selected_microdados_types) || "Sem tipos"}</span>
                      <span>{pipeline.schedule || "-"}</span>
                    </div>
                  </button>
                ))}
                {linkedPipelines.length === 0 ? <p className="muted">Nenhuma pipeline vinculada.</p> : null}
              </div>
            </Panel>
          </div>
        ) : (
          <Panel>
            <div className="empty-state">
              <p>Selecione uma conexão.</p>
            </div>
          </Panel>
        )}
      </section>
    );
  }

  return (
    <section className="page">
      <PageHeader
        title="Conexões"
        actions={
          <button type="button" onClick={() => navigate(CONNECTION_CREATE_ROUTE)}>
            Nova conexão
          </button>
        }
      />

      <Panel>
        <div className="record-list">
          {connections.map((instance) => (
            <button
              key={instance.connection_key}
              type="button"
              className="selection-item"
              onClick={() => onOpenConnection(instance.connection_key)}
            >
              <div className="selection-item-head">
                <strong>{instance.connection_name}</strong>
                <StatusBadge status={instance.validation_status || (instance.is_active ? "ready" : "pending")} />
              </div>
              <div className="selection-item-body">
                <span>{instance.connection_key}</span>
                <span>{instance.pipeline_count || 0} pipeline(s)</span>
                <span>{formatTimestamp(instance.updated_at)}</span>
              </div>
            </button>
          ))}

          {connections.length === 0 ? <p className="muted">Nenhuma conexão cadastrada.</p> : null}
        </div>
      </Panel>
    </section>
  );
}

function DashboardsPage({ dashboardId, setDashboardId, dashboardUrl, onLoadDashboard }) {
  return (
    <section className="page">
      <PageHeader title="Dashboards" actions={<ButtonLink href={METABASE_URL}>Abrir Metabase</ButtonLink>} />

      <Panel>
        <div className="toolbar-row">
          <label className="field compact-field">
            <span>Dashboard ID</span>
            <input type="number" min="1" value={dashboardId} onChange={(event) => setDashboardId(event.target.value)} />
          </label>
          <button type="button" onClick={() => onLoadDashboard(Number(dashboardId))}>
            Carregar
          </button>
        </div>
      </Panel>

      <Panel className="embed-panel">
        {dashboardUrl ? (
          <iframe title="metabase-dashboard" src={dashboardUrl} className="dashboard-frame" />
        ) : (
          <div className="empty-state">
            <p>Nenhum dashboard carregado.</p>
          </div>
        )}
      </Panel>
    </section>
  );
}

const DEFAULT_POSTGRES_SQL = "SELECT now();";
const SYSTEM_SCHEMAS = new Set(["pg_catalog", "information_schema"]);
const RELATION_CONTEXT_KEYWORDS = new Set(["from", "join", "update", "into", "table", "view"]);
const COLUMN_CONTEXT_KEYWORDS = new Set(["select", "where", "and", "or", "on", "order", "group", "by", "having", "set"]);
const SQL_FUNCTION_SUGGESTIONS = [
  { label: "now", detail: "function", insertText: "now()" },
  { label: "count", detail: "aggregate", insertText: "count(*)" },
  { label: "sum", detail: "aggregate", insertText: "sum()" },
  { label: "avg", detail: "aggregate", insertText: "avg()" },
  { label: "min", detail: "aggregate", insertText: "min()" },
  { label: "max", detail: "aggregate", insertText: "max()" },
  { label: "date_trunc", detail: "function", insertText: "date_trunc()" },
  { label: "coalesce", detail: "function", insertText: "coalesce()" },
  { label: "nullif", detail: "function", insertText: "nullif()" },
  { label: "round", detail: "function", insertText: "round()" },
];
const SQL_SUGGESTION_MAX_WIDTH = 420;
const SQL_SUGGESTION_MIN_WIDTH = 220;
const SQL_SUGGESTION_MAX_HEIGHT = 180;
const SQL_SUGGESTION_ROW_HEIGHT = 31;
const SQL_SUGGESTION_GAP = 8;

function getTokenRange(sql, cursorPosition) {
  const safeCursor = Math.max(0, Math.min(cursorPosition, sql.length));
  const isTokenCharacter = (character) => /[A-Za-z0-9_$.]/.test(character);

  let start = safeCursor;
  while (start > 0 && isTokenCharacter(sql[start - 1])) {
    start -= 1;
  }

  let end = safeCursor;
  while (end < sql.length && isTokenCharacter(sql[end])) {
    end += 1;
  }

  return {
    start,
    end,
    token: sql.slice(start, end),
  };
}

function getSqlEditorContext(sql, cursorPosition) {
  const beforeCursor = sql.slice(0, cursorPosition);
  const tokenRange = getTokenRange(sql, cursorPosition);
  const words = beforeCursor.toLowerCase().match(/[a-z_]+/g) || [];
  const previousWord = tokenRange.start === cursorPosition ? words.at(-1) || "" : words.at(-2) || "";
  const currentWord = tokenRange.token.toLowerCase();
  const qualifiedMatch = currentWord.match(/^([a-z_][a-z0-9_$]*)\.(.*)$/);

  return {
    qualifier: qualifiedMatch?.[1] || "",
    qualifiedToken: qualifiedMatch?.[2] || "",
    previousWord,
    currentWord,
    tokenRange,
  };
}

function getLineHeight(style) {
  const parsedLineHeight = Number.parseFloat(style.lineHeight);
  if (Number.isFinite(parsedLineHeight)) {
    return parsedLineHeight;
  }

  const parsedFontSize = Number.parseFloat(style.fontSize);
  return Number.isFinite(parsedFontSize) ? parsedFontSize * 1.5 : 22;
}

function getTextareaCaretPoint(textarea, position) {
  const style = window.getComputedStyle(textarea);
  const mirror = document.createElement("div");
  const marker = document.createElement("span");
  const mirroredProperties = [
    "boxSizing",
    "width",
    "borderTopWidth",
    "borderRightWidth",
    "borderBottomWidth",
    "borderLeftWidth",
    "paddingTop",
    "paddingRight",
    "paddingBottom",
    "paddingLeft",
    "fontFamily",
    "fontSize",
    "fontStyle",
    "fontWeight",
    "letterSpacing",
    "lineHeight",
    "textTransform",
    "textIndent",
    "tabSize",
  ];

  for (const property of mirroredProperties) {
    mirror.style[property] = style[property];
  }

  mirror.style.position = "absolute";
  mirror.style.top = "0";
  mirror.style.left = "-9999px";
  mirror.style.visibility = "hidden";
  mirror.style.whiteSpace = "pre-wrap";
  mirror.style.overflowWrap = "break-word";
  mirror.style.wordBreak = "normal";

  mirror.textContent = textarea.value.slice(0, position);
  marker.textContent = textarea.value.slice(position, position + 1) || ".";
  mirror.appendChild(marker);
  document.body.appendChild(mirror);

  const point = {
    left: marker.offsetLeft - textarea.scrollLeft,
    top: marker.offsetTop - textarea.scrollTop,
    lineHeight: getLineHeight(style),
  };

  mirror.remove();
  return point;
}

function getSqlSuggestionPosition(textarea, shell, suggestionCount = 0) {
  if (!textarea || !shell) {
    return null;
  }

  const cursorPosition = textarea.selectionStart ?? textarea.value.length;
  const caret = getTextareaCaretPoint(textarea, cursorPosition);
  const textareaTop = textarea.offsetTop;
  const textareaLeft = textarea.offsetLeft;
  const shellWidth = shell.clientWidth;
  const availableWidth = Math.max(160, shellWidth - SQL_SUGGESTION_GAP * 2);
  const textareaHeight = textarea.clientHeight;
  const width = Math.max(Math.min(SQL_SUGGESTION_MIN_WIDTH, availableWidth), Math.min(SQL_SUGGESTION_MAX_WIDTH, availableWidth));
  const maxLeft = Math.max(SQL_SUGGESTION_GAP, shellWidth - width - SQL_SUGGESTION_GAP);
  const left = Math.min(Math.max(textareaLeft + caret.left, SQL_SUGGESTION_GAP), maxLeft);
  const caretTop = textareaTop + caret.top;
  const caretBottom = caretTop + caret.lineHeight;
  const editorBottom = textareaTop + textareaHeight;
  const listHeight = suggestionCount
    ? Math.min(SQL_SUGGESTION_MAX_HEIGHT, Math.max(SQL_SUGGESTION_ROW_HEIGHT, suggestionCount * SQL_SUGGESTION_ROW_HEIGHT + 2))
    : SQL_SUGGESTION_MAX_HEIGHT;
  const spaceBelow = Math.max(0, editorBottom - caretBottom - SQL_SUGGESTION_GAP);
  const spaceAbove = Math.max(0, caretTop - textareaTop - SQL_SUGGESTION_GAP);
  const shouldOpenBelow = spaceBelow >= Math.min(96, listHeight) || spaceBelow >= spaceAbove;
  const maxHeight = shouldOpenBelow
    ? Math.min(listHeight, Math.max(SQL_SUGGESTION_ROW_HEIGHT, spaceBelow))
    : Math.min(listHeight, spaceAbove);
  const top = shouldOpenBelow
    ? caretBottom + SQL_SUGGESTION_GAP
    : Math.max(SQL_SUGGESTION_GAP, caretTop - maxHeight - SQL_SUGGESTION_GAP);

  return {
    left,
    maxHeight,
    top,
    width,
  };
}

function useSqlCatalog(catalogRows) {
  return useMemo(() => {
    const relationMap = new Map();
    const schemaSet = new Set();

    for (const row of catalogRows || []) {
      if (!row?.schema_name || !row?.relation_name || SYSTEM_SCHEMAS.has(row.schema_name)) {
        continue;
      }

      schemaSet.add(row.schema_name);
      const relationKey = `${row.schema_name}.${row.relation_name}`;
      if (!relationMap.has(relationKey)) {
        relationMap.set(relationKey, {
          key: relationKey,
          schema: row.schema_name,
          name: row.relation_name,
          type: row.relation_type,
          columns: [],
        });
      }

      if (row.column_name) {
        relationMap.get(relationKey).columns.push(row.column_name);
      }
    }

    const relations = [...relationMap.values()];
    const columns = relations.flatMap((relation) =>
      relation.columns.map((columnName) => ({
        key: `${relation.key}.${columnName}`,
        schema: relation.schema,
        relationName: relation.name,
        relationType: relation.type,
        name: columnName,
      })),
    );

    return {
      schemas: [...schemaSet].sort(),
      relations,
      columns,
    };
  }, [catalogRows]);
}

function SqlSuggestionList({ activeIndex, position, suggestions, onSelectSuggestion, suggestionListRef }) {
  if (!suggestions.length) {
    return null;
  }

  return (
    <div ref={suggestionListRef} className="sql-suggestion-list" style={position || undefined}>
      {suggestions.map((suggestion, index) => (
        <button
          key={suggestion.id}
          type="button"
          className={`sql-suggestion-item${index === activeIndex ? " active" : ""}`}
          data-suggestion-index={index}
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => onSelectSuggestion(suggestion)}
        >
          <strong>{suggestion.label}</strong>
          <span>{suggestion.detail}</span>
        </button>
      ))}
    </div>
  );
}

function SqlConsoleOutput({ error, query, result }) {
  return (
    <div className="sql-output">
      {query ? (
        <div className="sql-output-query">
          <span aria-hidden="true">&gt;</span>
          <pre>{query}</pre>
        </div>
      ) : null}

      {error ? (
        <div className="sql-output-error">{error}</div>
      ) : (
        <>
          <SqlResultsTable result={result} emptyMessage="A consulta PostgreSQL não retornou linhas." />
          {result ? (
            <p className="sql-row-count">
              {result.row_count} {result.row_count === 1 ? "row" : "rows"}
              {result.truncated ? ` (limit ${result.max_rows})` : ""}
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}

function SqlWorkspace({ adminRequest }) {
  const [localSql, setLocalSql] = useState(DEFAULT_POSTGRES_SQL);
  const [lastExecutedSql, setLastExecutedSql] = useState(DEFAULT_POSTGRES_SQL);
  const [localSqlResult, setLocalSqlResult] = useState(null);
  const [localSqlError, setLocalSqlError] = useState("");
  const [localSqlStatus, setLocalSqlStatus] = useState("syncing");
  const [catalogRows, setCatalogRows] = useState([]);
  const [cursorPosition, setCursorPosition] = useState(DEFAULT_POSTGRES_SQL.length);
  const [isSuggestionOpen, setIsSuggestionOpen] = useState(false);
  const [activeSuggestionIndex, setActiveSuggestionIndex] = useState(0);
  const [suggestionPosition, setSuggestionPosition] = useState(null);
  const editorRef = useRef(null);
  const editorShellRef = useRef(null);
  const sqlFormRef = useRef(null);
  const suggestionListRef = useRef(null);
  const suppressedSuggestionTokenRef = useRef("");
  const catalog = useSqlCatalog(catalogRows);
  const editorContext = useMemo(() => getSqlEditorContext(localSql, cursorPosition), [cursorPosition, localSql]);

  const currentSuggestions = useMemo(() => {
    const currentToken = editorContext.currentWord;
    const relationToken = editorContext.qualifiedToken;
    const schemaSuggestions = catalog.schemas.map((schemaName) => ({
      id: `schema:${schemaName}`,
      label: schemaName,
      detail: "schema",
      insertText: `${schemaName}.`,
      kind: "schema",
    }));
    const relationSuggestions = catalog.relations.map((relation) => ({
      id: `relation:${relation.key}`,
      label: `${relation.schema}.${relation.name}`,
      detail: relation.type,
      insertText: `${relation.schema}.${relation.name}`,
      kind: "relation",
    }));
    const columnSuggestions = catalog.columns.map((column) => ({
      id: `column:${column.key}`,
      label: column.name,
      detail: `${column.schema}.${column.relationName}`,
      insertText: column.name,
      kind: "column",
    }));
    const functionSuggestions = SQL_FUNCTION_SUGGESTIONS.map((item) => ({
      id: `function:${item.label}`,
      label: item.label,
      detail: item.detail,
      insertText: item.insertText,
      kind: "function",
    }));

    let source = [...relationSuggestions, ...schemaSuggestions, ...columnSuggestions, ...functionSuggestions];
    if (editorContext.qualifier) {
      source = relationSuggestions.filter((item) => item.label.toLowerCase().startsWith(`${editorContext.qualifier}.`));
    } else if (RELATION_CONTEXT_KEYWORDS.has(editorContext.previousWord)) {
      source = [...schemaSuggestions, ...relationSuggestions];
    } else if (COLUMN_CONTEXT_KEYWORDS.has(editorContext.previousWord)) {
      source = [...columnSuggestions, ...functionSuggestions];
    }

    const filterToken = editorContext.qualifier ? `${editorContext.qualifier}.${relationToken}` : currentToken;
    const filtered = filterToken
      ? source.filter((item) => item.label.toLowerCase().startsWith(filterToken))
      : source;

    return filtered.slice(0, 12);
  }, [
    catalog.columns,
    catalog.relations,
    catalog.schemas,
    editorContext.currentWord,
    editorContext.previousWord,
    editorContext.qualifiedToken,
    editorContext.qualifier,
  ]);

  function updateSuggestionPosition(target = editorRef.current) {
    setSuggestionPosition(getSqlSuggestionPosition(target, editorShellRef.current, currentSuggestions.length));
  }

  function suggestionSuppressionKey(sql, position) {
    const context = getSqlEditorContext(sql, position);
    return `${context.tokenRange.start}:${context.tokenRange.end}:${context.currentWord}`;
  }

  function openSuggestionsForToken(target) {
    const nextCursorPosition = target.selectionStart ?? target.value.length;
    const nextSuppressionKey = suggestionSuppressionKey(target.value, nextCursorPosition);

    if (suppressedSuggestionTokenRef.current === nextSuppressionKey) {
      return;
    }

    setIsSuggestionOpen(true);
    updateSuggestionPosition(target);
  }

  useLayoutEffect(() => {
    if (!isSuggestionOpen || !currentSuggestions.length) {
      setSuggestionPosition(null);
      return;
    }

    updateSuggestionPosition();
  }, [currentSuggestions.length, cursorPosition, isSuggestionOpen, localSql]);

  useEffect(() => {
    if (!isSuggestionOpen) {
      return undefined;
    }

    function handleResize() {
      updateSuggestionPosition();
    }

    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [isSuggestionOpen]);

  useEffect(() => {
    if (!currentSuggestions.length) {
      setActiveSuggestionIndex(0);
      return;
    }

    setActiveSuggestionIndex((currentIndex) => Math.min(currentIndex, currentSuggestions.length - 1));
  }, [currentSuggestions]);

  useEffect(() => {
    if (!isSuggestionOpen) {
      return;
    }

    const activeItem = suggestionListRef.current?.querySelector(`[data-suggestion-index="${activeSuggestionIndex}"]`);
    activeItem?.scrollIntoView({ block: "nearest" });
  }, [activeSuggestionIndex, isSuggestionOpen]);

  async function loadPostgresCatalog() {
    setLocalSqlError("");
    setLocalSqlStatus("syncing");

    try {
      const response = await adminRequest("/api/admin/sql/catalog");
      setCatalogRows(response.items || []);
      setLocalSqlStatus("ready");
    } catch (error) {
      setCatalogRows([]);
      setLocalSqlStatus("error");
      setLocalSqlError(error instanceof Error ? error.message : "Falha ao carregar o catalogo PostgreSQL.");
    }
  }

  useEffect(() => {
    let cancelled = false;

    async function loadInitialSqlState() {
      try {
        setLocalSqlStatus("syncing");
        const [catalogResponse, queryResponse] = await Promise.all([
          adminRequest("/api/admin/sql/catalog"),
          adminRequest("/api/admin/sql/query", {
            method: "POST",
            body: { sql: DEFAULT_POSTGRES_SQL, max_rows: 500 },
          }),
        ]);

        if (cancelled) {
          return;
        }
        setCatalogRows(catalogResponse.items || []);
        setLocalSqlResult(queryResponse);
        setLastExecutedSql(DEFAULT_POSTGRES_SQL);
        setLocalSqlStatus("ready");
      } catch (error) {
        if (!cancelled) {
          setLocalSqlStatus("error");
          setLocalSqlError(error instanceof Error ? error.message : "Falha ao conectar no PostgreSQL.");
        }
      }
    }

    loadInitialSqlState();

    return () => {
      cancelled = true;
    };
  }, [adminRequest]);

  async function handleRunLocalSql(event) {
    event.preventDefault();

    try {
      setLocalSqlError("");
      setLocalSqlStatus("syncing");
      const result = await adminRequest("/api/admin/sql/query", {
        method: "POST",
        body: { sql: localSql, max_rows: 500 },
      });
      setLocalSqlResult(result);
      setLastExecutedSql(localSql);
      setLocalSqlStatus("ready");
    } catch (error) {
      setLocalSqlResult(null);
      setLocalSqlStatus("error");
      setLocalSqlError(error instanceof Error ? error.message : "Falha ao executar a consulta PostgreSQL.");
    }
  }

  function handleEditorChange(event) {
    setLocalSql(event.target.value);
    setCursorPosition(event.target.selectionStart ?? event.target.value.length);
    setActiveSuggestionIndex(0);
    openSuggestionsForToken(event.target);
  }

  function handleEditorSelection(event) {
    setCursorPosition(event.target.selectionStart ?? 0);
    openSuggestionsForToken(event.target);
  }

  function handleEditorFocus(event) {
    openSuggestionsForToken(event.target);
  }

  function handleEditorScroll(event) {
    if (isSuggestionOpen) {
      updateSuggestionPosition(event.target);
    }
  }

  function handleSuggestionSelect(suggestion) {
    const target = editorRef.current;
    const { start, end } = getTokenRange(localSql, cursorPosition);
    const nextSql = `${localSql.slice(0, start)}${suggestion.insertText}${localSql.slice(end)}`;
    const nextCursor = start + suggestion.insertText.length;

    setLocalSql(nextSql);
    setCursorPosition(nextCursor);
    setIsSuggestionOpen(false);
    suppressedSuggestionTokenRef.current = "";

    window.requestAnimationFrame(() => {
      if (!target) {
        return;
      }

      target.focus();
      target.setSelectionRange(nextCursor, nextCursor);
    });
  }

  function insertEditorText(text) {
    const target = editorRef.current;
    const selectionStart = target?.selectionStart ?? cursorPosition;
    const selectionEnd = target?.selectionEnd ?? cursorPosition;
    const nextSql = `${localSql.slice(0, selectionStart)}${text}${localSql.slice(selectionEnd)}`;
    const nextCursor = selectionStart + text.length;

    setLocalSql(nextSql);
    setCursorPosition(nextCursor);
    suppressedSuggestionTokenRef.current = "";

    window.requestAnimationFrame(() => {
      if (!target) {
        return;
      }

      target.focus();
      target.setSelectionRange(nextCursor, nextCursor);
    });
  }

  function handleEditorKeyDown(event) {
    if (event.key === "Escape") {
      event.preventDefault();
      setIsSuggestionOpen(false);
      suppressedSuggestionTokenRef.current = suggestionSuppressionKey(localSql, cursorPosition);
      return;
    }

    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      insertEditorText("\n");
      return;
    }

    if (event.key === " " && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      if (currentSuggestions.length) {
        handleSuggestionSelect(currentSuggestions[activeSuggestionIndex] || currentSuggestions[0]);
      } else {
        suppressedSuggestionTokenRef.current = "";
        setIsSuggestionOpen(true);
        updateSuggestionPosition();
      }
      return;
    }

    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (localSqlStatus !== "syncing") {
        sqlFormRef.current?.requestSubmit();
      }
      return;
    }

    if (!isSuggestionOpen || !currentSuggestions.length) {
      return;
    }

    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveSuggestionIndex((currentIndex) => (currentIndex + 1) % currentSuggestions.length);
      return;
    }

    if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveSuggestionIndex((currentIndex) => (currentIndex - 1 + currentSuggestions.length) % currentSuggestions.length);
      return;
    }

    if (event.key === "Tab") {
      event.preventDefault();
      handleSuggestionSelect(currentSuggestions[activeSuggestionIndex] || currentSuggestions[0]);
      return;
    }

  }

  return (
    <section className="page sql-page">
      <div className="sql-console">
        <div className="sql-result-area">
          <SqlConsoleOutput error={localSqlError} query={lastExecutedSql} result={localSqlResult} />
        </div>

        <form ref={sqlFormRef} className="sql-console-form" onSubmit={handleRunLocalSql}>
          <div ref={editorShellRef} className="sql-editor-shell">
            <textarea
              ref={editorRef}
              aria-label="SQL"
              className="sql-editor-textarea"
              value={localSql}
              onChange={handleEditorChange}
              onFocus={handleEditorFocus}
              onBlur={() => setIsSuggestionOpen(false)}
              onClick={handleEditorSelection}
              onKeyDown={handleEditorKeyDown}
              onKeyUp={handleEditorSelection}
              onScroll={handleEditorScroll}
              onSelect={handleEditorSelection}
              placeholder={DEFAULT_POSTGRES_SQL}
              spellCheck={false}
            />
            {isSuggestionOpen && currentSuggestions.length ? (
              <SqlSuggestionList
                activeIndex={activeSuggestionIndex}
                position={suggestionPosition}
                suggestions={currentSuggestions}
                onSelectSuggestion={handleSuggestionSelect}
                suggestionListRef={suggestionListRef}
              />
            ) : null}
          </div>

          <div className="toolbar-row sql-console-toolbar">
            <button type="submit" disabled={localSqlStatus === "syncing"}>
              Executar SQL
            </button>
            <button type="button" className="secondary" onClick={loadPostgresCatalog} disabled={localSqlStatus === "syncing"}>
              Atualizar catálogo
            </button>
            <span className={`status-badge ${statusTone(localSqlStatus === "error" ? "error" : localSqlStatus === "ready" ? "ready" : "pending")}`}>
              {localSqlStatus === "ready" ? "Database pronto" : localSqlStatus === "error" ? "Erro no Banco" : "Consultando"}
            </span>
          </div>
        </form>
      </div>

      <div className="sql-shortcut-help" aria-label="Atalhos SQL">
        <span><kbd>Enter</kbd> executa</span>
        <span><kbd>Ctrl</kbd> + <kbd>Enter</kbd> nova linha</span>
        <span><kbd>Ctrl</kbd> + <kbd>Space</kbd> autocompleta</span>
        <span><kbd>Tab</kbd> autocompleta</span>
        <span><kbd>Esc</kbd> fecha sugestões</span>
      </div>
    </section>
  );
}

function SqlPage({ adminRequest }) {
  return <SqlWorkspace adminRequest={adminRequest} />;
}

export default function App() {
  const [route, setRoute] = useState(getRouteFromHash());
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [connectorDefinition, setConnectorDefinition] = useState(null);
  const [connections, setConnections] = useState([]);
  const [pipelines, setPipelines] = useState([]);
  const [selectedConnectionKey, setSelectedConnectionKey] = useState("");
  const [selectedPipelineKey, setSelectedPipelineKey] = useState("");
  const [connectionDetail, setConnectionDetail] = useState(null);
  const [pipelineDiagnostics, setPipelineDiagnostics] = useState(null);
  const [pipelineTimeline, setPipelineTimeline] = useState(null);
  const [dagRuns, setDagRuns] = useState([]);
  const [connectionForm, setConnectionForm] = useState(INITIAL_CONNECTION_FORM);
  const [pipelineForm, setPipelineForm] = useState(INITIAL_PIPELINE_FORM);
  const [createState, setCreateState] = useState("idle");
  const [pipelineAction, setPipelineAction] = useState("");
  const [deleteAction, setDeleteAction] = useState("");
  const [dashboardId, setDashboardId] = useState("");
  const [dashboardUrl, setDashboardUrl] = useState("");
  const [vannaQuestion, setVannaQuestion] = useState("");
  const [vannaResult, setVannaResult] = useState(null);
  const [vannaState, setVannaState] = useState("idle");
  const [vannaError, setVannaError] = useState("");

  const auth = useAdminAuth({ apiBaseUrl: API_BASE_URL, storageKey: "dataif.admin" });

  useEffect(() => {
    function handleHashChange() {
      setRoute(getRouteFromHash());
    }

    window.addEventListener("hashchange", handleHashChange);
    return () => window.removeEventListener("hashchange", handleHashChange);
  }, []);

  async function adminRequest(path, options = {}) {
    const token = await auth.getAccessToken();
    const response = await fetch(`${API_BASE_URL}${path}`, {
      method: options.method || "GET",
      headers: buildHeaders(token, options.body !== undefined),
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    });

    if (!response.ok) {
      const detailText = await response.text();
      throw new Error(detailText || `Falha HTTP ${response.status}`);
    }

    if (response.status === 204) {
      return null;
    }

    return response.json();
  }

  async function loadConnections() {
    if (auth.status !== "authenticated") {
      return;
    }

    try {
      setError("");
      const response = await adminRequest("/api/admin/connections/pnp");
      const nextConnections = response.items || [];
      setConnections(nextConnections);
      setSelectedConnectionKey((current) =>
        nextConnections.some((item) => item.connection_key === current) ? current : nextConnections[0]?.connection_key || "",
      );
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Falha ao carregar as conexoes.");
    }
  }

  async function loadPipelines() {
    if (auth.status !== "authenticated") {
      return;
    }

    try {
      setError("");
      const response = await adminRequest("/api/admin/pipelines/pnp");
      const nextPipelines = response.items || [];
      setPipelines(nextPipelines);
      setSelectedPipelineKey((current) =>
        nextPipelines.some((item) => item.instance_key === current) ? current : nextPipelines[0]?.instance_key || "",
      );
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Falha ao carregar as pipelines.");
    }
  }

  async function loadConnectorDefinition() {
    if (auth.status !== "authenticated") {
      return;
    }

    try {
      setError("");
      const definition = await adminRequest("/api/admin/connector-definitions/pnp");
      setConnectorDefinition(definition);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Falha ao carregar o catalogo da PNP.");
    }
  }

  async function loadSelectedConnection(connectionKey) {
    if (!connectionKey || auth.status !== "authenticated") {
      setConnectionDetail(null);
      return;
    }

    try {
      const detailResponse = await adminRequest(`/api/admin/connections/pnp/${connectionKey}`);
      setConnectionDetail(detailResponse);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Falha ao carregar a conexão.");
    }
  }

  async function loadSelectedPipeline(instanceKey) {
    if (!instanceKey || auth.status !== "authenticated") {
      setPipelineDiagnostics(null);
      setPipelineTimeline(null);
      setDagRuns([]);
      return;
    }

    // Cada secao busca e atualiza seu proprio estado assim que resolve, em vez de
    // esperar as outras -- diagnostics/timeline/dag-runs sao independentes entre si.
    await Promise.allSettled([
      adminRequest(`/api/admin/pipelines/pnp/${instanceKey}/diagnostics`)
        .then((response) => setPipelineDiagnostics(response))
        .catch((requestError) => {
          setError(requestError instanceof Error ? requestError.message : "Falha ao carregar o diagnostico da pipeline.");
        }),
      adminRequest(`/api/admin/pipelines/pnp/${instanceKey}/timeline`)
        .then((response) => setPipelineTimeline(response))
        .catch((requestError) => {
          setError(requestError instanceof Error ? requestError.message : "Falha ao carregar a timeline da pipeline.");
        }),
      adminRequest(`/api/admin/pipelines/pnp/${instanceKey}/dag-runs`)
        .then((response) => setDagRuns(response.items || []))
        .catch((requestError) => {
          setError(requestError instanceof Error ? requestError.message : "Falha ao carregar as execucoes da pipeline.");
        }),
    ]);
  }

  useEffect(() => {
    if (auth.status === "authenticated") {
      loadConnections();
      loadPipelines();
      return;
    }

    setConnections([]);
    setPipelines([]);
    setConnectorDefinition(null);
    setSelectedConnectionKey("");
    setSelectedPipelineKey("");
    setConnectionDetail(null);
    setPipelineDiagnostics(null);
    setPipelineTimeline(null);
    setDagRuns([]);
  }, [auth.status]);

  useEffect(() => {
    if (auth.status !== "authenticated") {
      return;
    }

    if (route === PIPELINE_CREATE_ROUTE) {
      loadConnectorDefinition();
    }
  }, [route, auth.status]);

  useEffect(() => {
    if (route !== PIPELINE_CREATE_ROUTE) {
      return;
    }

    const pendingConnection = window.sessionStorage.getItem("dataif.connection.selected");
    if (pendingConnection) {
      setPipelineForm((current) => ({ ...current, connection_key: pendingConnection }));
      return;
    }

    if (!pipelineForm.connection_key && selectedConnectionKey) {
      setPipelineForm((current) => ({ ...current, connection_key: current.connection_key || selectedConnectionKey }));
    }
  }, [route, selectedConnectionKey, pipelineForm.connection_key]);

  useEffect(() => {
    loadSelectedConnection(selectedConnectionKey);
  }, [selectedConnectionKey, auth.status]);

  useEffect(() => {
    loadSelectedPipeline(selectedPipelineKey);
  }, [selectedPipelineKey, auth.status]);

  function requestAdminLogin(targetRoute = route) {
    storeReturnRoute(targetRoute);
    navigate(LOGIN_ROUTE);
  }

  async function handleAdminLogin(username, password) {
    const success = await auth.login(username, password);
    if (success) {
      navigate(consumeReturnRoute());
    }
  }

  function handleLoginBack() {
    navigate(auth.status === "authenticated" ? consumeReturnRoute() : "/");
  }

  async function handleSubmitConnection(event) {
    event.preventDefault();
    setCreateState("loading");
    setNotice("");
    setError("");

    try {
      const created = await adminRequest("/api/admin/connections/pnp", {
        method: "POST",
        body: connectionForm,
      });
      setConnectionForm(INITIAL_CONNECTION_FORM);
      setNotice(`conexão ${created.connection_name} criada com sucesso.`);
      await loadConnections();
      setSelectedConnectionKey(created.connection_key);
      navigate(CONNECTION_DETAIL_ROUTE);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Falha ao criar conexão.");
    } finally {
      setCreateState("idle");
    }
  }

  async function handleSubmitPipeline(event) {
    event.preventDefault();
    setCreateState("loading");
    setNotice("");
    setError("");

    try {
      const created = await adminRequest("/api/admin/pipelines/pnp", {
        method: "POST",
        body: pipelineForm,
      });
      setPipelineForm(INITIAL_PIPELINE_FORM);
      window.sessionStorage.removeItem("dataif.connection.selected");
      setNotice(`Pipeline ${created.instance_name} criada com sucesso.`);
      await loadPipelines();
      setSelectedPipelineKey(created.instance_key);
      navigate("/pipelines");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Falha ao criar pipeline.");
    } finally {
      setCreateState("idle");
    }
  }

  async function handleTriggerOperation(operation) {
    if (!selectedPipelineKey) {
      return;
    }

    setPipelineAction(operation);
    setNotice("");
    setError("");

    try {
      const response = await adminRequest(
        `/api/admin/pipelines/pnp/${selectedPipelineKey}/operations/${operation}`,
        { method: "POST" },
      );
      setNotice(`Operacao ${response.dag_id} disparada para ${response.instance_key}.`);
      await loadSelectedPipeline(selectedPipelineKey);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Falha ao disparar pipeline.");
    } finally {
      setPipelineAction("");
    }
  }

  async function handleLoadDashboard(targetDashboardId) {
    if (!Number.isFinite(targetDashboardId) || targetDashboardId < 1) {
      setError("Informe um ID de dashboard valido.");
      return;
    }

    try {
      setError("");
      setNotice("");
      const payload = await adminRequest("/api/admin/embed/metabase-default", {
        method: "POST",
        body: { dashboard_id: targetDashboardId, params: {} },
      });
      setDashboardId(String(payload.dashboard_id));
      setDashboardUrl(payload.signed_url);
      setNotice(`Dashboard ${payload.dashboard_id} definido como padrao do sistema.`);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Falha ao carregar dashboard.");
    }
  }

  async function handleLoadDefaultDashboard() {
    try {
      setError("");
      const payload = await fetch(`${API_BASE_URL}/api/embed/metabase-default`).then(async (response) => {
        if (!response.ok) {
          throw new Error(await response.text());
        }
        return response.json();
      });
      setDashboardId(String(payload.dashboard_id));
      setDashboardUrl(payload.signed_url);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Falha ao carregar dashboard.");
    }
  }

  async function handleAskVanna(event) {
    event.preventDefault();
    const question = vannaQuestion.trim();
    if (question.length < 3) {
      return;
    }

    setVannaState("loading");
    setVannaError("");

    try {
      let headers = { "Content-Type": "application/json" };
      if (auth.status === "authenticated") {
        const token = await auth.getAccessToken();
        headers = buildHeaders(token, true);
      }
      const payload = await fetch(`${API_BASE_URL}/api/vanna/ask`, {
        method: "POST",
        headers,
        body: JSON.stringify({ question }),
      }).then(async (response) => {
        if (!response.ok) {
          throw new Error(await response.text());
        }
        return response.json();
      });
      setVannaResult(payload);
    } catch (requestError) {
      setVannaError(requestError instanceof Error ? requestError.message : "Falha ao consultar o Vanna.");
      setVannaResult(null);
    } finally {
      setVannaState("idle");
    }
  }

  async function handleDeletePipeline(instanceKey) {
    if (!instanceKey || !window.confirm("Excluir esta pipeline?")) {
      return;
    }

    setDeleteAction(instanceKey);
    setNotice("");
    setError("");

    try {
      const response = await adminRequest(`/api/admin/pipelines/pnp/instances/${instanceKey}`, { method: "DELETE" });
      setNotice(`Pipeline ${response.instance_name} excluida com sucesso.`);
      setSelectedPipelineKey("");
      setPipelineDiagnostics(null);
      setPipelineTimeline(null);
      setDagRuns([]);
      await loadPipelines();
      await loadConnections();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Falha ao excluir pipeline.");
    } finally {
      setDeleteAction("");
    }
  }

  async function handleDeleteConnection(instanceKey) {
    if (!instanceKey || !window.confirm("Excluir esta conexão?")) {
      return;
    }

    setDeleteAction(instanceKey);
    setNotice("");
    setError("");

    try {
      const response = await adminRequest(`/api/admin/connections/pnp/${instanceKey}`, { method: "DELETE" });
      setNotice(`conexão ${response.connection_name} excluida com sucesso.`);
      setSelectedConnectionKey("");
      setConnectionDetail(null);
      setSelectedPipelineKey("");
      setPipelineDiagnostics(null);
      setPipelineTimeline(null);
      setDagRuns([]);
      await loadConnections();
      await loadPipelines();
      navigate(CONNECTIONS_ROUTE);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Falha ao excluir conexão.");
    } finally {
      setDeleteAction("");
    }
  }

  useEffect(() => {
    if (route === "/" || (route === "/dashboards" && !dashboardUrl)) {
      handleLoadDefaultDashboard();
    }
  }, [route]);

  const isAuthenticated = auth.status === "authenticated";
  const publicNavItems = NAV_ITEMS.filter((item) => item.path === "/" || isAuthenticated || !AUTH_REQUIRED_NAV_PATHS.has(item.path));
  const isVisitorBlockedRoute = !isAuthenticated && AUTH_REQUIRED_NAV_PATHS.has(route);

  const homeContent = (
    <HomePage
      dashboardUrl={dashboardUrl}
      vannaQuestion={vannaQuestion}
      setVannaQuestion={setVannaQuestion}
      vannaResult={vannaResult}
      vannaState={vannaState}
      vannaError={vannaError}
      onAskVanna={handleAskVanna}
    />
  );

  let content = homeContent;

  if (isVisitorBlockedRoute) {
    content = homeContent;
  }

  if (!isVisitorBlockedRoute && (route === "/pipelines" || route === PIPELINE_CREATE_ROUTE)) {
    content = (
      <PipelinesPage
        auth={auth}
        route={route}
        onLoginRequest={() => requestAdminLogin(route)}
        pipelines={pipelines}
        connections={connections}
        selectedPipelineKey={selectedPipelineKey}
        onSelectPipeline={setSelectedPipelineKey}
        diagnosticsOverview={pipelineDiagnostics}
        timelineOverview={pipelineTimeline}
        dagRuns={dagRuns}
        pipelineAction={pipelineAction}
        deleteAction={deleteAction}
        onTriggerOperation={handleTriggerOperation}
        onDeletePipeline={handleDeletePipeline}
        pipelineForm={pipelineForm}
        setPipelineForm={setPipelineForm}
        createState={createState}
        onSubmitPipeline={handleSubmitPipeline}
        connectorDefinition={connectorDefinition}
      />
    );
  }

  if (!isVisitorBlockedRoute && [CONNECTIONS_ROUTE, CONNECTION_CREATE_ROUTE, CONNECTION_DETAIL_ROUTE].includes(route)) {
    content = (
      <ConnectionsPage
        auth={auth}
        route={route}
        onLoginRequest={() => requestAdminLogin(route)}
        connectionForm={connectionForm}
        setConnectionForm={setConnectionForm}
        createState={createState}
        onSubmitConnection={handleSubmitConnection}
        connections={connections}
        selectedConnectionKey={selectedConnectionKey}
        detail={connectionDetail}
        onOpenConnection={(connectionKey) => {
          setSelectedConnectionKey(connectionKey);
          navigate(CONNECTION_DETAIL_ROUTE);
        }}
        onOpenPipeline={(pipelineKey) => {
          setSelectedPipelineKey(pipelineKey);
          navigate("/pipelines");
        }}
        deleteAction={deleteAction}
        onDeleteConnection={handleDeleteConnection}
      />
    );
  }

  if (!isVisitorBlockedRoute && route === "/dashboards") {
    content = (
      <DashboardsPage
        dashboardId={dashboardId}
        setDashboardId={setDashboardId}
        dashboardUrl={dashboardUrl}
        onLoadDashboard={handleLoadDashboard}
      />
    );
  }

  if (!isVisitorBlockedRoute && route === "/sql") {
    content = (
      <SqlPage adminRequest={adminRequest} />
    );
  }

  if (isAdminRoute(route)) {
    content = (
      <AdminWorkspacePage
        auth={auth}
        route={route}
        onLoginRequest={() => requestAdminLogin(route)}
        onLogout={auth.logout}
      />
    );
  }

  if (route === LOGIN_ROUTE) {
    content = <LoginPage auth={auth} onSubmit={handleAdminLogin} onBack={handleLoginBack} />;
  }

  if (route === SETTINGS_ROUTE) {
    content = (
      <SettingsPage
        auth={auth}
        onLoginRequest={() => requestAdminLogin(SETTINGS_ROUTE)}
        onLogout={auth.logout}
      />
    );
  }

  if (route === ADMIN_SETTINGS_ROUTE) {
    content = (
      <AdminSettingsPage
        auth={auth}
        onLoginRequest={() => requestAdminLogin(ADMIN_SETTINGS_ROUTE)}
        adminRequest={adminRequest}
      />
    );
  }

  return (
    <main className="app-shell">
      <AppHeader
        auth={auth}
        adminNavItems={ADMIN_NAV_ITEMS}
        githubRepoUrl={GITHUB_REPO_URL}
        onAdminSettings={() => navigate(ADMIN_SETTINGS_ROUTE)}
        onLogout={auth.logout}
        onRequestLogin={() => requestAdminLogin(route)}
        onSelectRoute={navigate}
        publicNavItems={publicNavItems}
        route={route}
      />

      <div className="content-shell">
        {notice ? <p className="notice-banner">{notice}</p> : null}
        {error || auth.error ? <p className="error-banner">{error || auth.error}</p> : null}
        {content}
      </div>
    </main>
  );
}
