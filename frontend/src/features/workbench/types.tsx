import React from "react";
import { BriefcaseBusiness, Database, Radar, ShieldCheck } from "lucide-react";

export type Step = "holdings" | "risk" | "evidence" | "audit";

export const STEPS: { key: Step; label: string; icon: React.ReactNode }[] = [
  { key: "holdings", label: "输入持仓", icon: <BriefcaseBusiness size={18} /> },
  { key: "risk", label: "风险分析", icon: <Radar size={18} /> },
  { key: "evidence", label: "证据链", icon: <Database size={18} /> },
  { key: "audit", label: "审稿复盘", icon: <ShieldCheck size={18} /> },
];
