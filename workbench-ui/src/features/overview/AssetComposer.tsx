import { useEffect, useMemo, useState } from "react";
import { Check, Plus, Search, X } from "lucide-react";
import type { Asset } from "../../api/types";
import { useCreateAssetMutation, useLatestResearchUniverseQuery } from "../../hooks/useWorkbenchQueries";
import { useI18n } from "../../i18n";
import { useWorkbenchStore } from "../../state/workbenchStore";
import { CN_RESEARCH_UNIVERSE, type CNResearchCandidate } from "./cnResearchUniverse";

interface AssetComposerProps {
  open: boolean;
  assets: Asset[];
  onClose(): void;
}

export function AssetComposer({ open, assets, onClose }: AssetComposerProps) {
  const { l, term } = useI18n();
  const mode = useWorkbenchStore((state) => state.mode);
  const setSelectedAssetId = useWorkbenchStore((state) => state.setSelectedAssetId);
  const mutation = useCreateAssetMutation();
  const researchUniverse = useLatestResearchUniverseQuery();
  const [query, setQuery] = useState("");
  const [selectedCandidate, setSelectedCandidate] = useState<CNResearchCandidate | null>(null);
  const universe = useMemo(() => {
    if (mode !== "research" || !researchUniverse.data?.symbols.length) {
      return CN_RESEARCH_UNIVERSE;
    }
    const known = new Map(CN_RESEARCH_UNIVERSE.map((item) => [item.ticker, item]));
    return researchUniverse.data.symbols.map((item) => {
      const named = known.get(item.symbol);
      return {
        ticker: item.symbol,
        name: named?.name ?? (item.name && item.name !== item.symbol ? item.name : l("名称待补充", "Name pending")),
        exchange: item.exchange,
        assetType: item.asset_type,
        frozenResultAvailable: item.frozen_result_available,
        trainingEligible: item.training_eligible,
        rowCount: item.row_count,
        provider: item.provider
      } satisfies CNResearchCandidate;
    }).sort((left, right) => {
      if (left.frozenResultAvailable !== right.frozenResultAvailable) return left.frozenResultAvailable ? -1 : 1;
      const leftNamed = !left.name.includes("待补充") && left.name !== "Name pending";
      const rightNamed = !right.name.includes("待补充") && right.name !== "Name pending";
      if (leftNamed !== rightNamed) return leftNamed ? -1 : 1;
      return left.ticker.localeCompare(right.ticker);
    });
  }, [l, mode, researchUniverse.data]);
  const equityCount = universe.filter((item) => item.assetType === "equity").length;
  const etfCount = universe.filter((item) => item.assetType === "etf").length;

  const modePayload = {
    demo: { data_mode: "demo", source_type: "synthetic", source_name: "demo-ui" },
    sandbox: { data_mode: "sandbox", source_type: "synthetic", source_name: "sandbox-ui" },
    research: { data_mode: "real", source_type: "backfilled", source_name: "cn-research-pit-ui" },
    real: { data_mode: "real", source_type: "manual_override", source_name: "frontend-intake" }
  } as const;

  const candidates = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return universe.filter((candidate) =>
      needle ? `${candidate.ticker} ${candidate.name}`.toLowerCase().includes(needle) : true
    );
  }, [query, universe]);

  const existingCandidate = selectedCandidate
    ? assets.find((asset) => asset.ticker === selectedCandidate.ticker)
    : undefined;

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setSelectedCandidate(null);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  const chooseCandidate = (candidate: CNResearchCandidate) => {
    setSelectedCandidate(candidate);
  };

  const submitCandidate = async () => {
    if (!selectedCandidate) return;
    if (existingCandidate) {
      setSelectedAssetId(existingCandidate.id);
      onClose();
      return;
    }
    const asset = await mutation.mutateAsync({
      ticker: selectedCandidate.ticker,
      name: selectedCandidate.name,
      asset_type: selectedCandidate.assetType,
      currency: mode === "research" ? "CNY" : "USD",
      exchange: selectedCandidate.exchange,
      ...modePayload[mode],
      observed_at: new Date().toISOString(),
      confidence: 0.95
    });
    setSelectedAssetId(asset.id);
    onClose();
  };

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="asset-composer-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="asset-composer-title"
        data-testid="asset-composer-modal"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="asset-composer-modal__header">
          <div>
            <div className="eyebrow">{l("固定研究池", "Fixed research pool")}</div>
            <h2 id="asset-composer-title">{l("添加研究对象", "Add research asset")}</h2>
          </div>
          <button className="modal-close-button" type="button" aria-label={l("关闭", "Close")} onClick={onClose}>
            <X size={18} aria-hidden="true" />
          </button>
        </header>

        <label className="asset-search asset-composer-modal__search" htmlFor="candidate-search-input">
          <Search size={15} aria-hidden="true" />
          <input
            id="candidate-search-input"
            autoFocus
            data-testid="candidate-search-input"
            placeholder={l("输入名称或证券代码，例如：贵州茅台、600519", "Search name or ticker, e.g. Kweichow Moutai or 600519")}
            value={query}
            onChange={(event) => {
              const value = event.target.value;
              setQuery(value);
              const normalized = value.trim().toLowerCase();
              setSelectedCandidate(
                universe.find((candidate) => candidate.ticker.toLowerCase() === normalized || candidate.name.toLowerCase() === normalized) ?? null
              );
            }}
          />
        </label>

        <p className="asset-composer-modal__hint">
          {l(
            `当前可检索已有历史行情的 ${equityCount} 只股票和 ${etfCount} 只 ETF。研究任务将为所有通过质量门禁的标的生成结果，不再只限制流动性前几名。`,
            `Search ${equityCount} equities and ${etfCount} ETFs with historical prices. Research runs cover every asset that passes the quality gate.`
          )}
        </p>

        <div className="asset-candidate-list__summary">
          <span>{query.trim() ? l(`找到 ${candidates.length} 个结果`, `${candidates.length} results`) : l("优先显示已有研究结果和名称完整的标的", "Showing assets with results and complete names first")}</span>
          <small>{l("点击一行即可选中", "Click a row to select")}</small>
        </div>
        <div className="asset-candidate-list" role="listbox" aria-label={l("可添加的研究对象", "Available research assets")}>
          {candidates.map((candidate) => {
            const alreadyAdded = assets.some((asset) => asset.ticker === candidate.ticker);
            const selected = selectedCandidate?.ticker === candidate.ticker;
            return (
              <button
                key={candidate.ticker}
                className={`asset-candidate ${selected ? "asset-candidate--selected" : ""}`}
                type="button"
                role="option"
                aria-selected={selected}
                onClick={() => chooseCandidate(candidate)}
              >
                <span>
                  <strong>{candidate.ticker}</strong>
                  <small>{candidate.name}</small>
                </span>
                <span className="asset-candidate__meta">
                  <span>{candidate.exchange} · {term(candidate.assetType)}</span>
                  <span>{candidate.frozenResultAvailable ? l("已有研究结果", "Research result available") : l("历史行情可用", "Price history available")}{candidate.rowCount ? ` · ${candidate.rowCount.toLocaleString()} ${l("日线", "daily bars")}` : ""}</span>
                  {alreadyAdded ? <span>{l("已添加", "Added")}</span> : null}
                  <i className="asset-candidate__check" aria-hidden="true"><Check size={14} /></i>
                </span>
              </button>
            );
          })}
          {candidates.length === 0 ? (
            <div className="asset-candidate-empty">
              <Search size={20} aria-hidden="true" />
              <strong>{l("没有匹配的研究对象", "No matching research asset")}</strong>
              <span>{l("请尝试输入六位证券代码或中文名称。", "Try a six-digit ticker or a Chinese security name.")}</span>
            </div>
          ) : null}
        </div>

        <footer className="asset-composer-modal__footer">
          <span className="muted">
            {selectedCandidate
              ? `${selectedCandidate.ticker} · ${selectedCandidate.name}`
              : l("请选择一个研究对象", "Select a research asset")}
          </span>
          <button
            className="primary-button"
            type="button"
            data-testid="confirm-add-asset"
            disabled={!selectedCandidate || mutation.isPending}
            onClick={() => void submitCandidate()}
          >
            <Plus size={16} aria-hidden="true" />
            {mutation.isPending
              ? l("正在添加…", "Adding...")
              : existingCandidate
                ? l("选择已有对象", "Select existing")
                : l("添加到研究范围", "Add to research scope")}
          </button>
        </footer>

        {mutation.error instanceof Error ? (
          <p className="asset-composer-modal__error">{mutation.error.message}</p>
        ) : null}
      </section>
    </div>
  );
}
