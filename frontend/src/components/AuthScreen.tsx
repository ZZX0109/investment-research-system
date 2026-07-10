import React, { useState } from "react";
import { LogIn, UserPlus } from "lucide-react";
import { passwordPolicyErrors } from "./utils";

const PASSWORD_POLICY = "至少 8 位，并包含小写字母、大写字母、数字和特殊字符。";

interface AuthScreenProps {
  booting: boolean;
  error: string | null;
  onSubmit: (mode: "login" | "register", email: string, password: string) => Promise<void>;
}

export default function AuthScreen({ booting, error, onSubmit }: AuthScreenProps) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (mode === "register") {
      const errors = passwordPolicyErrors(password);
      if (errors.length) {
        setLocalError(`密码不符合规则：${errors.join("、")}。${PASSWORD_POLICY}`);
        return;
      }
    }
    setSubmitting(true);
    setLocalError(null);
    try {
      await onSubmit(mode, email, password);
    } catch (err) {
      setLocalError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="center-shell">
      <section className="auth-card">
        <div className="brand center-brand">
          <span className="brand-mark">IA</span>
          <div>
            <strong>Investment Agent Workflow</strong>
            <span>个人投研 Agent</span>
          </div>
        </div>
        <div>
          <p className="eyebrow">账户先行 · 前测后生成 · 持仓驱动</p>
          <h1>先建立你的投研账户</h1>
          <p className="muted-text">之前像静态 PPT，是因为系统直接加载了演示组合。现在必须登录、完成偏好前测并录入持仓后，才会调用行情和证据链接口。</p>
          <p className="muted-text">密码规则参考 ANDFlow：{PASSWORD_POLICY}</p>
        </div>
        <div className="auth-tabs">
          <button className={mode === "login" ? "selected" : ""} onClick={() => setMode("login")} type="button">
            <LogIn size={16} /> 登录
          </button>
          <button className={mode === "register" ? "selected" : ""} onClick={() => setMode("register")} type="button">
            <UserPlus size={16} /> 注册
          </button>
        </div>
        <form className="form-grid" onSubmit={submit}>
          <label>
            邮箱
            <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" required />
          </label>
          <label>
            密码
            <input
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              type="password"
              minLength={8}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              title={PASSWORD_POLICY}
              required
            />
          </label>
          <button className="primary-button" disabled={submitting || booting} type="submit">
            {submitting || booting ? null : mode === "login" ? <LogIn size={17} /> : <UserPlus size={17} />}
            {submitting || booting ? "处理中..." : mode === "login" ? "进入系统" : "创建账户"}
          </button>
        </form>
        {error || localError ? <p className="form-error">{localError ?? error}</p> : null}
      </section>
    </main>
  );
}
