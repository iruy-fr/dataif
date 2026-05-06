import { useEffect, useRef, useState } from "react";

import { Moon01, Sun } from "@untitledui/icons";

import avatarPlaceholder from "@/assets/avatar_placeholder.png";
import githubLogo from "@/assets/github_logo_icon_229278.svg";
import ifLogo from "@/assets/if-logo.png";
import { useTheme } from "@/providers/theme-provider";

function routeToHref(path) {
  return `#${path}`;
}

function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const isDark = theme === "dark";
  const Icon = isDark ? Sun : Moon01;

  return (
    <button
      type="button"
      className="icon-button"
      onClick={() => setTheme(isDark ? "light" : "dark")}
      title={isDark ? "Ativar modo claro" : "Ativar modo escuro"}
      aria-label={isDark ? "Ativar modo claro" : "Ativar modo escuro"}
    >
      <Icon className="size-5" />
    </button>
  );
}

function HeaderLogo() {
  return (
    <a className="app-brand" href={routeToHref("/")}>
      <span className="app-brand-mark">
        <img src={ifLogo} alt="Instituto Federal" />
      </span>
      <span className="app-brand-label">DataIF</span>
    </a>
  );
}

function NavLink({ item, active }) {
  return (
    <a className={`nav-link${active ? " active" : ""}`} href={routeToHref(item.path)}>
      {item.label}
    </a>
  );
}

function AccountMenu({ adminNavItems, auth, onAdminSettings, onLogout, onRequestLogin, onSelectRoute }) {
  const accountLabel =
    auth.claims?.preferred_username ||
    auth.claims?.email ||
    (auth.status === "authenticated" ? "Administrador" : "Convidado");
  const [isOpen, setIsOpen] = useState(false);
  const menuRef = useRef(null);

  useEffect(() => {
    function handlePointerDown(event) {
      if (!menuRef.current?.contains(event.target)) {
        setIsOpen(false);
      }
    }

    function handleEscape(event) {
      if (event.key === "Escape") {
        setIsOpen(false);
      }
    }

    window.addEventListener("mousedown", handlePointerDown);
    window.addEventListener("keydown", handleEscape);

    return () => {
      window.removeEventListener("mousedown", handlePointerDown);
      window.removeEventListener("keydown", handleEscape);
    };
  }, []);

  return (
    <div className="account-menu" ref={menuRef}>
      <button
        type="button"
        className="icon-button avatar-button"
        onClick={() => setIsOpen((current) => !current)}
        aria-label="Abrir menu do usuario"
        aria-expanded={isOpen}
      >
        <img src={avatarPlaceholder} alt="" />
      </button>

      {isOpen ? (
        <div className="account-dropdown">
          <div className="account-dropdown-head">
            <strong>{accountLabel}</strong>
            <span>{auth.status === "authenticated" ? "Sessao ativa" : "Acesso visitante"}</span>
          </div>

          {auth.status === "authenticated" ? (
            <>
              <div className="account-dropdown-group">
                <button
                  type="button"
                  className="account-dropdown-item"
                  onClick={() => {
                    setIsOpen(false);
                    onSelectRoute("/configuracoes");
                  }}
                >
                  Conta
                </button>
                {adminNavItems.map((item) => (
                  <button
                    key={item.path}
                    type="button"
                    className="account-dropdown-item"
                    onClick={() => {
                      setIsOpen(false);
                      onSelectRoute(item.path);
                    }}
                  >
                    {item.label}
                  </button>
                ))}
                <button
                  type="button"
                  className="account-dropdown-item"
                  onClick={() => {
                    setIsOpen(false);
                    onAdminSettings();
                  }}
                >
                  Configuracoes Admin
                </button>
              </div>

              <button
                type="button"
                className="account-dropdown-item account-dropdown-item-danger"
                onClick={() => {
                  setIsOpen(false);
                  onLogout();
                }}
              >
                Sair
              </button>
            </>
          ) : (
            <button
              type="button"
              className="account-dropdown-item"
              onClick={() => {
                setIsOpen(false);
                onRequestLogin();
              }}
              disabled={auth.status === "loading"}
            >
              {auth.status === "loading" ? "Verificando..." : "Login"}
            </button>
          )}
        </div>
      ) : null}
    </div>
  );
}

function HeaderActions({ adminNavItems, auth, githubRepoUrl, onAdminSettings, onLogout, onRequestLogin, onSelectRoute }) {
  return (
    <>
      <ThemeToggle />
      <a
        className="icon-button"
        href={githubRepoUrl}
        target="_blank"
        rel="noreferrer"
        aria-label="GitHub"
        title="GitHub"
      >
        <img src={githubLogo} alt="" className="github-icon" />
      </a>
      <AccountMenu
        adminNavItems={adminNavItems}
        auth={auth}
        onAdminSettings={onAdminSettings}
        onLogout={onLogout}
        onRequestLogin={onRequestLogin}
        onSelectRoute={onSelectRoute}
      />
    </>
  );
}

export default function AppHeader({
  auth,
  githubRepoUrl,
  adminNavItems,
  onAdminSettings,
  onLogout,
  onRequestLogin,
  onSelectRoute,
  publicNavItems,
  route,
}) {
  return (
    <header className="app-header">
      <div className="app-header-inner">
        <div className="app-header-top">
          <HeaderLogo />
          <div className="app-header-actions">
            <HeaderActions
              adminNavItems={adminNavItems}
              auth={auth}
              githubRepoUrl={githubRepoUrl}
              onAdminSettings={onAdminSettings}
              onLogout={onLogout}
              onRequestLogin={onRequestLogin}
              onSelectRoute={onSelectRoute}
            />
          </div>
        </div>

        <div className="app-header-navs">
          <nav className="nav-row" aria-label="Navegacao principal">
            {publicNavItems.map((item) => (
              <NavLink key={item.path} item={item} active={route === item.path} />
            ))}
          </nav>
        </div>
      </div>
    </header>
  );
}
