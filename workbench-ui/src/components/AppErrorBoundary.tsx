import React from "react";

interface Props {
  children: React.ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * A provider response must never be able to take down the whole workbench.
 * The boundary is intentionally small: it keeps the rest of the page usable
 * and gives the user an actionable recovery path instead of a white screen.
 */
export class AppErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // Keep the browser console useful for local diagnosis without exposing
    // credentials or request payloads in the UI.
    console.error("Workbench rendering error", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <main className="app-error-state" role="alert">
        <div className="app-error-state__card">
          <span className="eyebrow">研究页面</span>
          <h1>页面暂时无法显示</h1>
          <p>AI 服务返回的数据格式异常，或本次研究响应未完成。研究数据不会因此丢失。</p>
          <p className="app-error-state__detail">{this.state.error.message || "未知页面错误"}</p>
          <button className="primary-button" type="button" onClick={() => window.location.reload()}>
            刷新页面
          </button>
        </div>
      </main>
    );
  }
}
