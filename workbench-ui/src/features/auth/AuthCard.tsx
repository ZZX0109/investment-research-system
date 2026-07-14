import { InlineNotice } from "../../components/InlineNotice";
import { Panel } from "../../components/Panel";
import { useWorkbenchStore } from "../../state/workbenchStore";
import { useAuthSession } from "./useAuthSession";

export function AuthCard() {
  const mode = useWorkbenchStore((state) => state.mode);
  const auth = useAuthSession();
  const usesSeededSession = auth.usesSeededSession;

  if (auth.session?.user) {
    return (
      <Panel eyebrow="Session" title={auth.session.user.display_name}>
        <p className="muted">{auth.session.user.email}</p>
        <p className="muted mono">{auth.session.user.auth_subject}</p>
        {!usesSeededSession ? (
          <div className="button-row">
            <button className="ghost-button" type="button" onClick={() => void auth.submitLogout()}>
              {auth.isLoggingOut ? "Signing Out..." : "Logout"}
            </button>
          </div>
        ) : null}
      </Panel>
    );
  }

  return (
    <Panel eyebrow="Session" title={usesSeededSession ? (mode === "demo" ? "Demo Session" : "Sandbox Session") : "Real Login"}>
      {usesSeededSession ? (
        <p className="muted">
          {mode === "demo"
            ? "Demo mode seeds a stable investor identity so the whole workflow is explorable."
            : "Sandbox mode uses a seeded analyst identity so synthetic experiments stay isolated from real accounts."}
        </p>
      ) : (
        <form
          className="form-stack"
          onSubmit={(event) => {
            event.preventDefault();
            void (auth.form.formMode === "register" ? auth.submitRegister() : auth.submitLogin());
          }}
        >
          <div className="button-row">
            <button
              className={auth.form.formMode === "login" ? "primary-button" : "ghost-button"}
              type="button"
              onClick={() => auth.setFormMode("login")}
            >
              Login
            </button>
            <button
              className={auth.form.formMode === "register" ? "primary-button" : "ghost-button"}
              type="button"
              onClick={() => auth.setFormMode("register")}
            >
              Register
            </button>
          </div>
          <label>
            <span>Email</span>
            <input value={auth.form.email} onChange={(event) => auth.setEmail(event.target.value)} />
          </label>
          <label>
            <span>Password</span>
            <input type="password" value={auth.form.password} onChange={(event) => auth.setPassword(event.target.value)} />
          </label>
          {auth.form.formMode === "register" ? (
            <label>
              <span>Display Name</span>
              <input value={auth.form.displayName} onChange={(event) => auth.setDisplayName(event.target.value)} />
            </label>
          ) : null}
          <div className="button-row">
            <button className="primary-button" type="submit">
              {auth.form.formMode === "register"
                ? auth.isRegistering
                  ? "Registering..."
                  : "Register"
                : auth.isLoggingIn
                  ? "Logging In..."
                  : "Login"}
            </button>
          </div>
          {auth.form.lastError ? (
            <InlineNotice title="Auth Request Failed" tone="warn" body={auth.form.lastError} />
          ) : null}
          {auth.status === "error" && auth.sessionError ? (
            <InlineNotice title="Session Unavailable" tone="warn" body={auth.sessionError} />
          ) : null}
        </form>
      )}
    </Panel>
  );
}
