import { createWorkbenchClient } from "../api/client";
import { useWorkbenchStore } from "../state/workbenchStore";

export function useWorkbenchClient() {
  const mode = useWorkbenchStore((state) => state.mode);
  return createWorkbenchClient(mode);
}
