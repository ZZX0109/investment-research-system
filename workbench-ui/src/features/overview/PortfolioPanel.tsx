import { useDeferredValue, useState } from "react";
import { Plus, Search } from "lucide-react";
import { Panel } from "../../components/Panel";
import { SourceBadge } from "../../components/SourceBadge";
import { useAssetsQuery, useCreatePositionMutation, usePositionsQuery, useWatchlistsQuery } from "../../hooks/useWorkbenchQueries";
import { useWorkbenchStore } from "../../state/workbenchStore";

export function PortfolioPanel() {
  const assetsQuery = useAssetsQuery();
  const positionsQuery = usePositionsQuery();
  const watchlistsQuery = useWatchlistsQuery();
  const selectedAssetId = useWorkbenchStore((state) => state.selectedAssetId);
  const setSelectedAssetId = useWorkbenchStore((state) => state.setSelectedAssetId);
  const assetSearch = useWorkbenchStore((state) => state.assetSearch);
  const setAssetSearch = useWorkbenchStore((state) => state.setAssetSearch);
  const deferredSearch = useDeferredValue(assetSearch);
  const createPosition = useCreatePositionMutation();
  const [quantity, setQuantity] = useState("1");
  const [costBasis, setCostBasis] = useState("0");

  const assets = (assetsQuery.data ?? []).filter((asset) => {
    const needle = deferredSearch.trim().toLowerCase();
    return needle ? `${asset.ticker} ${asset.name}`.toLowerCase().includes(needle) : true;
  });

  return (
    <Panel eyebrow="Research universe" title="研究对象">
      <label className="asset-search" htmlFor="asset-search-input">
        <Search size={15} aria-hidden="true" />
        <input
          id="asset-search-input"
          data-testid="asset-search-input"
          placeholder="搜索代码或名称"
          value={assetSearch}
          onChange={(event) => setAssetSearch(event.target.value)}
        />
      </label>
      <div className="asset-list">
        {assets.map((asset) => (
          <button
            key={asset.id}
            data-testid={`asset-card-${asset.ticker.toLowerCase()}`}
            className={`asset-card ${selectedAssetId === asset.id ? "asset-card--active" : ""}`}
            type="button"
            onClick={() => setSelectedAssetId(asset.id)}
          >
            <div>
              <strong>{asset.ticker}</strong>
              <div className="muted">{asset.name}</div>
              <small className="asset-card__meta">{asset.exchange ?? "CN"} · {asset.asset_type} · {asset.status}</small>
            </div>
            <SourceBadge provenance={asset.provenance} />
          </button>
        ))}
      </div>
      <div className="metric-strip">
        <div className="metric-card">
          <div className="eyebrow">Positions</div>
          <div className="metric-card__value">{positionsQuery.data?.length ?? 0}</div>
        </div>
        <div className="metric-card">
          <div className="eyebrow">Watchlists</div>
          <div className="metric-card__value">{watchlistsQuery.data?.length ?? 0}</div>
        </div>
      </div>
      <div className="position-composer">
        <label><span>Quantity</span><input inputMode="decimal" value={quantity} onChange={(event) => setQuantity(event.target.value)} /></label>
        <label><span>Cost basis</span><input inputMode="decimal" value={costBasis} onChange={(event) => setCostBasis(event.target.value)} /></label>
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
          <Plus size={16} aria-hidden="true" /><span>Add holding</span>
        </button>
      </div>
    </Panel>
  );
}
