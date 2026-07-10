import { useState } from "react";
import type { Step } from "../features/workbench/types";

export function useDashboardState() {
  const [selectedSymbol, setSelectedSymbol] = useState("");
  const [currentStep, setCurrentStep] = useState<Step>("holdings");
  const [uploadState, setUploadState] = useState("等待上传财报/研报");
  const [error, setError] = useState<string | null>(null);
  const [apiState, setApiState] = useState<"loading" | "live" | "fallback">("loading");

  return {
    selectedSymbol,
    setSelectedSymbol,
    currentStep,
    setCurrentStep,
    uploadState,
    setUploadState,
    error,
    setError,
    apiState,
    setApiState,
  };
}
