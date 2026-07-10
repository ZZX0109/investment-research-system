import React from "react";
import AuthScreen from "./components/AuthScreen";
import SetupScreen from "./components/SetupScreen";
import WorkbenchPage from "./features/workbench/WorkbenchPage";
import { useWorkbenchController } from "./features/workbench/useWorkbenchController";

export default function App() {
  const controller = useWorkbenchController();

  if (!controller.token || !controller.user || !controller.profile) {
    return <AuthScreen booting={controller.booting} error={controller.error} onSubmit={controller.handleAuth} />;
  }

  if (!controller.profile.onboardingCompleted) {
    return (
      <SetupScreen
        user={controller.user}
        preference={controller.preference}
        apiKeys={controller.apiKeys}
        token={controller.token}
        onPreferenceChange={controller.setPreference}
        onSubmit={controller.handleOnboarding}
        onLogout={controller.logout}
        onApiKeyChange={controller.refreshApiKeys}
      />
    );
  }

  if (!controller.portfolio || !controller.research) {
    return (
      <main className="center-shell">
        <section className="auth-card">
          <div className="brand center-brand">
            <span className="brand-mark">IA</span>
            <div>
              <strong>Investment Agent Workflow</strong>
              <span>正在生成你的投研驾驶舱</span>
            </div>
          </div>
          <p className="muted-text">正在拉取用户持仓、行情源和证据链。若外部行情接口失败，系统会显示不可用状态，不会伪造实时结论。</p>
        </section>
      </main>
    );
  }

  return (
    <WorkbenchPage
      apiKeys={controller.apiKeys}
      apiState={controller.apiState}
      currentStep={controller.currentStep}
      error={controller.error}
      portfolio={controller.portfolio}
      preference={controller.preference}
      profile={controller.profile}
      refreshReview={controller.refreshReview}
      research={controller.research}
      selectedSymbol={controller.selectedSymbol}
      token={controller.token}
      uploadState={controller.uploadState}
      user={controller.user}
      onApiKeyChange={controller.refreshApiKeys}
      onCurrentStepChange={controller.setCurrentStep}
      onDocumentUpload={controller.handleDocumentUpload}
      onLogout={controller.logout}
      onPreferenceChange={controller.setPreference}
      onRefreshDaily={controller.handleRefreshDaily}
      onReportFrequencyChange={controller.updateReportFrequency}
      onSelectedSymbolChange={controller.setSelectedSymbol}
    />
  );
}
