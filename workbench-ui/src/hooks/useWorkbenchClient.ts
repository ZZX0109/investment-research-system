import { createWorkbenchClient } from "../api/client";
import { useWorkbenchStore } from "../state/workbenchStore";
import { useMemo } from "react";

export function useWorkbenchClient() {
  const mode = useWorkbenchStore((state) => state.mode);
  // Share one transport per mode so concurrent protected queries reuse the
  // same refresh lock instead of issuing a refresh per component.
  return useMemo(() => createWorkbenchClient(mode), [mode]);
}
