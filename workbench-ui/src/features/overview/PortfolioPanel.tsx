import { useCallback, useDeferredValue, useState } from "react";
import { Plus, Search, Trash2 } from "lucide-react";
import { Panel } from "../../components/Panel";
import { SourceBadge } from "../../components/SourceBadge";
import {
  useAssetsQuery,
  useCreatePositionMutation,
  useDeleteAssetMutation,
  usePositionsQuery,
  useWatchlistsQuery
} from "../../hooks/useWorkbenchQueries";
import { useI18n } from "../../i18n";
import { useWorkbenchStore } from "../../state/workbenchStore";
import { AssetComposer } from "./AssetComposer";

export function PortfolioPanel() {
  const { l, term } = useI18n();
  const assetsQuery = useAssetsQuery();
  const positionsQuery = usePositionsQuery();
  const watchlistsQuery = useWatchlistsQuery();
  const selectedAssetId = useWorkbenchStore((state) => state.selectedAssetId);
  const mode = useWorkbenchStore((state) => state.mode);
  const setSelectedAssetId = useWorkbenchStore((state) => state.setSelectedAssetId);
  const assetSearch = useWorkbenchStore((state) => state.assetSearch);
  const setAssetSearch = useWorkbenchStore((state) => state.setAssetSearch);
  const deferredSearch = useDeferredValue(assetSearch);
  const createPosition = useCreatePositionMutation();
  const deleteAsset = useDeleteAssetMutation();
  const [quantity, setQuantity] = useState("1");
  const [costBasis, setCostBasis] = useState("0");
  const [composerOpen, setComposerOpen] = useState(false);
  const closeComposer = useCallback(() => setComposerOpen(false), []);

  const assets = (assetsQuery.data ?? []).filter((asset) => {
    const needle = deferredSearch.trim().toLowerCase();
    return needle ? `${asset.ticker} ${asset.name}`.toLowerCase().includes(needle) : true;
  });

  return (
    <Panel eyebrow={l("研究范围", "Research universe")} title={l("研究对象", "Research assets")}>
      <label className="asset-search" htmlFor="asset-search-input">
        <Search size={15} aria-hidden="true" />
        <input
          id="asset-search-input"
          data-testid="asset-search-input"
          placeholder={l("搜索已添加的代码或名称", "Search added ticker or name")}
          value={assetSearch}
          onChange={(event) => setAssetSearch(event.target.value)}
        />
      </label>
      <button
        className="add-research-asset-button"
        type="button"
        data-testid="open-asset-composer"
        onClick={() => setComposerOpen(true)}
      >
        <Plus size={16} aria-hidden="true" />
        <span>{l("添加研究对象", "Add research asset")}</span>
      </button>
      <div className="asset-list">
        {assets.map((asset) => (
          <div className="asset-card-shell" key={asset.id}>
            <button
              data-testid={`asset-card-${asset.ticker.toLowerCase()}`}
              className={`asset-card ${selectedAssetId === asset.id ? "asset-card--active" : ""}`}
              type="button"
              onClick={() => setSelectedAssetId(asset.id)}
            >
              <div>
                <strong>{asset.ticker}</strong>
                <div className="muted">{asset.name}</div>
                <small className="asset-card__meta">{asset.exchange ?? "CN"} · {term(asset.asset_type)} · {term(asset.status)}</small>
              </div>
              <SourceBadge provenance={asset.provenance} />
            </button>
            <button
              className="asset-card__delete"
              type="button"
              aria-label={l(`删除 ${asset.ticker} ${asset.name}`, `Delete ${asset.ticker} ${asset.name}`)}
              title={l("仅从当前工作区移除；其他用户和历史研究证据不受影响", "Remove only from this workspace; other users and historical evidence are unaffected")}
              disabled={deleteAsset.isPending}
              onClick={() => {
                void deleteAsset.mutateAsync(asset.id).then(() => {
                  if (selectedAssetId === asset.id) setSelectedAssetId(null);
                });
              }}
            >
              <Trash2 size={14} aria-hidden="true" />
              <span>{l("删除", "Delete")}</span>
            </button>
          </div>
        ))}
        {(assetsQuery.data ?? []).length === 0 ? (
          <div className="asset-list-empty">
            <strong>{l("还没有研究对象", "No research assets yet")}</strong>
            <span>{l("点击上方“添加研究对象”，从固定研究池中选择。", "Use “Add research asset” above to select from the fixed research pool.")}</span>
          </div>
        ) : assets.length === 0 ? (
          <div className="asset-list-empty">
            <strong>{l("没有匹配结果", "No matching results")}</strong>
            <span>{l("请更换代码或名称关键词。", "Try another ticker or name.")}</span>
          </div>
        ) : null}
      </div>
      {deleteAsset.error instanceof Error ? (
        <p className="asset-action-error">{deleteAsset.error.message}</p>
      ) : null}
      {mode !== "research" ? (
        <>
          <div className="metric-strip">
            <div className="metric-card">
              <div className="eyebrow">{l("持仓", "Positions")}</div>
              <div className="metric-card__value">{positionsQuery.data?.length ?? 0}</div>
            </div>
            <div className="metric-card">
              <div className="eyebrow">{l("观察列表", "Watchlists")}</div>
              <div className="metric-card__value">{watchlistsQuery.data?.length ?? 0}</div>
            </div>
          </div>
          <div className="position-composer">
            <label><span>{l("数量", "Quantity")}</span><input inputMode="decimal" value={quantity} onChange={(event) => setQuantity(event.target.value)} /></label>
            <label><span>{l("成本价", "Cost basis")}</span><input inputMode="decimal" value={costBasis} onChange={(event) => setCostBasis(event.target.value)} /></label>
            <button
              className="icon-button"
              type="button"
              disabled={!selectedAssetId || createPosition.isPending || Number(quantity) <= 0}
              onClick={() => selectedAssetId && createPosition.mutate({
                asset_id: selectedAssetId,
                quantity: Number(quantity),
                cost_basis: Math.max(0, Number(costBasis)),
                opened_at: new Date().toISOString()
              })}
            >
              <Plus size={16} aria-hidden="true" /><span>{l("加入持仓", "Add holding")}</span>
            </button>
          </div>
        </>
      ) : null}
      <AssetComposer
        open={composerOpen}
        assets={assetsQuery.data ?? []}
        onClose={closeComposer}
      />
    </Panel>
  );
}
