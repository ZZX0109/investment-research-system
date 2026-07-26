import { InlineNotice } from "../../components/InlineNotice";
import { Panel } from "../../components/Panel";
import { useI18n } from "../../i18n";
import { useWorkbenchStore } from "../../state/workbenchStore";
import { useAuthSession } from "./useAuthSession";
import { ArrowLeft } from "lucide-react";

export function AuthCard() {
  const { l, term } = useI18n();
  const mode = useWorkbenchStore((state) => state.mode);
  const auth = useAuthSession();
  const usesSeededSession = auth.usesSeededSession;

  if (auth.session?.user) {
    return (
      <Panel eyebrow={l("用户会话", "Session")} title={term(auth.session.user.display_name)}>
        <div className="auth-session-summary">
          <p className="muted">{auth.session.user.email}</p>
          {mode !== "research" ? <p className="muted mono">{auth.session.user.auth_subject}</p> : null}
        </div>
        {!usesSeededSession ? (
          <div className="button-row">
            <button className="ghost-button" type="button" onClick={() => void auth.submitLogout()}>
              {auth.isLoggingOut ? l("正在退出…", "Signing Out...") : l("退出登录", "Logout")}
            </button>
          </div>
        ) : null}
      </Panel>
    );
  }

  const isRegistering = auth.form.formMode === "register";
  const realAuthTitle = isRegistering ? l("用户注册", "User registration") : l("用户登录", "User login");

  return (
    <Panel
      eyebrow={l("用户会话", "Session")}
      title={usesSeededSession
        ? (mode === "demo" ? l("演示会话", "Demo Session") : l("沙盒会话", "Sandbox Session"))
        : isRegistering ? (
          <span className="auth-title-with-back">
            <button
              className="auth-back-button"
              type="button"
              aria-label={l("返回登录", "Back to login")}
              data-testid="auth-back-to-login"
              onClick={() => auth.setFormMode("login")}
            >
              <ArrowLeft size={17} strokeWidth={2.2} aria-hidden="true" />
            </button>
            {realAuthTitle}
          </span>
        ) : realAuthTitle}
    >
      {usesSeededSession ? (
        <p className="muted">
          {mode === "demo"
            ? l("演示模式使用固定身份，方便完整体验流程。", "Demo mode seeds a stable investor identity so the whole workflow is explorable.")
            : l("沙盒模式使用固定分析员身份，使合成实验与真实账户隔离。", "Sandbox mode uses a seeded analyst identity so synthetic experiments stay isolated from real accounts.")}
        </p>
      ) : (
        <form
          className="form-stack"
          onSubmit={(event) => {
            event.preventDefault();
            void (auth.form.formMode === "register" ? auth.submitRegister() : auth.submitLogin());
          }}
        >
          <label>
            <span>{l("邮箱", "Email")}</span>
            <input value={auth.form.email} onChange={(event) => auth.setEmail(event.target.value)} />
          </label>
          <label>
            <span>{l("密码", "Password")}</span>
            <input type="password" value={auth.form.password} onChange={(event) => auth.setPassword(event.target.value)} />
          </label>
          {auth.form.formMode === "register" ? (
            <label>
              <span>{l("显示名称", "Display Name")}</span>
              <input value={auth.form.displayName} onChange={(event) => auth.setDisplayName(event.target.value)} />
            </label>
          ) : null}
          <div className="auth-submit-row">
            <button className="primary-button" type="submit">
              {auth.form.formMode === "register"
                ? auth.isRegistering
                  ? l("正在注册…", "Registering...")
                  : l("注册", "Register")
                : auth.isLoggingIn
                  ? l("正在登录…", "Logging In...")
                  : l("登录", "Login")}
            </button>
            {!isRegistering ? (
              <button
                className="auth-inline-link"
                type="button"
                data-testid="auth-register-link"
                onClick={() => auth.setFormMode("register")}
              >
                {l("注册", "Register")}
              </button>
            ) : null}
          </div>
          {auth.form.lastError ? (
            <InlineNotice title={l("认证请求失败", "Auth Request Failed")} tone="warn" body={auth.form.lastError} />
          ) : null}
          {auth.status === "error" && auth.sessionError ? (
            <InlineNotice title={l("会话不可用", "Session Unavailable")} tone="warn" body={auth.sessionError} />
          ) : null}
        </form>
      )}
    </Panel>
  );
}
