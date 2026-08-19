import type { ReactNode } from "react";
import { createPortal } from "react-dom";

/** Render application dialogs outside header/panel stacking contexts. */
export function ModalPortal({ children }: { children: ReactNode }) {
  if (typeof document === "undefined") return null;
  return createPortal(children, document.body);
}
