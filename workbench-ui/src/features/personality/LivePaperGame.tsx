import { Activity, AlertTriangle, Clock3, Coins, Newspaper, RefreshCw, ShoppingCart, Trophy, WalletCards, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useCancelPaperGameOrderMutation, useConfirmPaperGameOnboardingMutation, useCreatePaperGameAccountMutation, useCreatePaperGameOrderMutation, usePaperGameAccountQuery, usePaperGameEquityCurveQuery, usePaperGameLeaderboardQuery, usePaperGameOnboardingQuery, usePaperGameTodayQuery } from "../../hooks/useWorkbenchQueries";
import type { PaperGameAsset, PaperGameOnboarding } from "../../api/types";

const money = (value: number | null | undefined) => value == null ? "—" : `¥${value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}`;
const time = (value: string | null | undefined) => value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "尚未更新";

export function LivePaperGame({ personaCode }: { personaCode?: string | null }) {
  const today = usePaperGameTodayQuery();
  const createAccount = useCreatePaperGameAccountMutation();
  const [ready, setReady] = useState(false);
  const account = usePaperGameAccountQuery(ready);
  const onboarding = usePaperGameOnboardingQuery(ready);
  const leaderboard = usePaperGameLeaderboardQuery(ready);
  const curve = usePaperGameEquityCurveQuery(ready);
  const createOrder = useCreatePaperGameOrderMutation();
  const cancelOrder = useCancelPaperGameOrderMutation();
  const [category, setCategory] = useState<"全部" | PaperGameAsset["category"]>("全部");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [orderMode, setOrderMode] = useState<"quantity" | "amount">("quantity");
  const [quantity, setQuantity] = useState(100);
  const [amount, setAmount] = useState(10_000);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    createAccount.mutate(personaCode ?? null, { onSuccess: () => setReady(true) });
    // The server-side anonymous cookie makes this operation idempotent.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const assets = today.data?.assets ?? [];
  const filtered = [...(category === "全部" ? assets : assets.filter((item) => item.category === category))]
    .filter((item) => `${item.display_name}${item.symbol}${item.sector}`.toLowerCase().includes(query.toLowerCase()))
    .sort((left, right) => Number(right.latest_price != null) - Number(left.latest_price != null));
  const selected = assets.find((item) => item.symbol === selectedSymbol) ?? filtered[0] ?? null;
  useEffect(() => { if (!selectedSymbol && filtered[0]) setSelectedSymbol(filtered[0].symbol); }, [filtered, selectedSymbol]);
  const position = account.data?.positions.find((item) => item.symbol === selected?.symbol);
  const pending = account.data?.orders.filter((item) => ["pending", "open"].includes(item.status)) ?? [];
  const curveData = useMemo(() => (curve.data?.points ?? []).map((point) => ({ ...point, label: new Date(point.captured_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }) })), [curve.data]);

  const submit = (side: "buy" | "sell") => {
    if (!selected) return;
    setMessage(null);
    createOrder.mutate({ symbol: selected.symbol, side, idempotency_key: `${crypto.randomUUID()}-${Date.now()}`, ...(side === "buy" && orderMode === "amount" ? { amount } : { quantity }) }, {
      onSuccess: (order) => setMessage(order.status === "filled" ? `已模拟成交：${order.alias} ${order.quantity}份` : order.status === "rejected" ? order.rejection_reason : "委托已提交，开市后将按有效延迟报价处理"),
      onError: (error) => setMessage(error instanceof Error ? error.message : "委托提交失败")
    });
  };

  if (today.isLoading || createAccount.isPending) return <section className="live-paper-game live-paper-game--loading"><RefreshCw className="spin" size={20} />正在恢复今日模拟赛…</section>;
  if (today.isError || createAccount.isError) return <section className="live-paper-game live-paper-game--error"><AlertTriangle size={20} /><div><b>模拟赛暂时无法连接</b><p>{today.error instanceof Error ? today.error.message : createAccount.error instanceof Error ? createAccount.error.message : "请稍后刷新重试"}</p></div></section>;

  if (account.data?.setup_status === "setup_required") return <InitialPortfolio onboarding={onboarding.data} loading={onboarding.isLoading} />;
  const visible = filtered.slice(page * 24, page * 24 + 24);
  const pages = Math.max(1, Math.ceil(filtered.length / 24));
  return <section className="live-paper-game" data-testid="live-paper-game">
    <div className="live-paper-game__status"><div><Activity size={18} /><b>今日模拟赛 · {today.data?.trade_date}</b><span className={today.data?.market_open ? "is-open" : "is-closed"}>{today.data?.market_open ? "交易时段" : "休市 / 委托排队"}</span></div><small><Clock3 size={13} />{today.data?.quote_policy}</small></div>
    <div className="live-paper-game__summary"><Metric label="总资产" value={money(account.data?.total_equity)} /><Metric label="可用现金" value={money(account.data?.cash)} /><Metric label="持仓市值" value={money(account.data?.market_value)} /><Metric label="累计收益" value={`${(account.data?.total_return_pct ?? 0) >= 0 ? "+" : ""}${account.data?.total_return_pct ?? 0}%`} tone={(account.data?.total_return_pct ?? 0) >= 0 ? "up" : "down"} /><Metric label="模拟费用" value={money(account.data?.fees)} /></div>
    <div className="live-paper-game__grid">
      <article className="live-paper-game__bulletin"><span className="personality-lab__kicker"><Newspaper size={15} /> 今日公告</span>{(today.data?.bulletins ?? []).map((item) => <div key={`${item.title}-${item.published_at}`}><h3>{item.title}</h3><p>{item.detail}</p><small>{item.source} · {time(item.published_at)}</small></div>)}</article>
      <article className="live-paper-game__market"><div className="live-paper-game__section-title"><span className="personality-lab__kicker"><Coins size={15} /> 今日实名市场</span><div>{(["全部", "股票", "基金", "黄金"] as const).map((item) => <button type="button" className={category === item ? "is-active" : ""} onClick={() => { setCategory(item); setPage(0); setSelectedSymbol(null); }} key={item}>{item}</button>)}</div></div><input aria-label="搜索真实股票" placeholder="搜索名称、代码或行业" value={query} onChange={(event) => { setQuery(event.target.value); setPage(0); }} /><div className="live-paper-game__asset-list">{visible.map((asset) => <button type="button" key={asset.symbol} className={selected?.symbol === asset.symbol ? "is-active" : ""} onClick={() => setSelectedSymbol(asset.symbol)}><span><b>{asset.display_name} · {asset.symbol}</b><small>{asset.category} · {asset.sector}</small></span><span><b>{money(asset.latest_price)}</b><small className={(asset.change_pct ?? 0) >= 0 ? "is-up" : "is-down"}>{asset.change_pct == null ? "无行情" : `${asset.change_pct >= 0 ? "+" : ""}${asset.change_pct.toFixed(2)}%`}</small></span></button>)}</div><div className="live-paper-game__pager"><button type="button" disabled={page === 0} onClick={() => setPage(page - 1)}>上一页</button><small>{page + 1} / {pages}</small><button type="button" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>下一页</button></div></article>
      <article className="live-paper-game__order"><span className="personality-lab__kicker"><ShoppingCart size={15} /> 模拟委托</span>{selected ? <><div className="live-paper-game__quote"><div><b>{selected.display_name} · {selected.symbol}</b><small>{selected.category} · 每手{selected.lot_size}份</small></div><strong>{money(selected.latest_price)}</strong></div><div className="live-paper-game__quote-meta"><span>行情时间：{time(selected.captured_at)}</span><span>{selected.t_plus_one ? "股票 T+1 可卖" : "ETF按比赛规则处理"}</span></div>{selected.price_history.length > 1 && <div className="live-paper-game__price-chart"><ResponsiveContainer width="100%" height={105}><LineChart data={selected.price_history}><YAxis domain={["auto", "auto"]} hide /><Tooltip labelFormatter={(value) => time(String(value))} formatter={(value) => money(Number(value))} /><Line type="monotone" dataKey="price" stroke="#6b49cb" strokeWidth={2} dot={false} /></LineChart></ResponsiveContainer></div>}{!selected.tradable && <p className="live-paper-game__warning"><AlertTriangle size={14} />{selected.unavailable_reason ?? "当前休市，委托将排队"}</p>}<div className="live-paper-game__position-line"><span>持有 {position?.quantity ?? 0}</span><span>可卖 {position?.available_quantity ?? 0}</span><span>成本 {money(position?.average_cost)}</span></div><div className="live-paper-game__mode"><button type="button" className={orderMode === "quantity" ? "is-active" : ""} onClick={() => setOrderMode("quantity")}>按数量</button><button type="button" className={orderMode === "amount" ? "is-active" : ""} onClick={() => setOrderMode("amount")}>按金额买入</button></div>{orderMode === "quantity" ? <label>数量<input type="number" min={selected.lot_size} step={selected.lot_size} value={quantity} onChange={(event) => setQuantity(Math.max(selected.lot_size, Number(event.target.value)))} /></label> : <label>目标金额<input type="number" min={1000} step={1000} value={amount} onChange={(event) => setAmount(Math.max(1000, Number(event.target.value)))} /></label>}<div className="live-paper-game__trade-actions"><button type="button" disabled={createOrder.isPending} onClick={() => submit("buy")}>模拟买入</button><button type="button" disabled={createOrder.isPending || !position?.available_quantity || orderMode === "amount"} onClick={() => submit("sell")}>模拟卖出</button></div>{message && <p className="live-paper-game__message">{message}</p>}</> : <p>今日暂无可展示资产。</p>}</article>
    </div>
    <div className="live-paper-game__lower">
      <article><span className="personality-lab__kicker"><WalletCards size={15} /> 我的持仓</span>{account.data?.positions.length ? <div className="live-paper-game__positions">{account.data.positions.map((item) => <div key={item.symbol}><span><b>{item.alias}</b><small>{item.quantity}份 · 可卖{item.available_quantity}</small></span><span><b>{money(item.market_value)}</b><small className={item.unrealized_pnl >= 0 ? "is-up" : "is-down"}>{item.unrealized_pnl >= 0 ? "+" : ""}{money(item.unrealized_pnl)}</small></span></div>)}</div> : <p>还没有持仓，可以从股票、基金和黄金中建立模拟组合。</p>}{pending.length > 0 && <div className="live-paper-game__pending"><b>待成交委托</b>{pending.map((order) => <div key={order.id}><span>{order.side === "buy" ? "买入" : "卖出"} {order.alias} {order.quantity}份</span><button type="button" aria-label="撤销委托" onClick={() => cancelOrder.mutate(order.id)}><X size={13} /></button></div>)}</div>}</article>
      <article><span className="personality-lab__kicker"><Activity size={15} /> 账户净值</span><div className="live-paper-game__chart">{curveData.length ? <ResponsiveContainer width="100%" height={210}><LineChart data={curveData}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="label" /><YAxis domain={["auto", "auto"]} /><Tooltip formatter={(value) => money(Number(value))} /><Line type="monotone" dataKey="total_equity" stroke="#2563eb" strokeWidth={2} dot={false} /></LineChart></ResponsiveContainer> : <p>产生第一笔账户快照后，这里会显示净值变化。</p>}</div></article>
      <article><span className="personality-lab__kicker"><Trophy size={15} /> 人格排行榜</span><small>{leaderboard.data?.metric}</small><div className="live-paper-game__ranking">{leaderboard.data?.entries.slice(0, 13).map((item) => <div key={item.code} className={item.is_user ? "is-user" : ""}><b>#{item.rank}</b><span>{item.emoji} {item.name}</span><span className={item.return_pct >= 0 ? "is-up" : "is-down"}>{item.return_pct >= 0 ? "+" : ""}{item.return_pct}%</span><small>回撤 {item.max_drawdown_pct}%</small></div>)}</div></article>
    </div>
    <p className="live-paper-game__disclaimer">{today.data?.disclaimer} 标的名称和行情仅用于虚拟学习体验；不提供真实开户、入金、提现或买卖建议。</p>
  </section>;
}

function InitialPortfolio({ onboarding, loading }: { onboarding?: PaperGameOnboarding; loading: boolean }) {
  const confirm = useConfirmPaperGameOnboardingMutation();
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Record<string, number>>({});
  if (loading || !onboarding) return <section className="live-paper-game live-paper-game--loading"><RefreshCw className="spin" size={20} />正在准备昨日收盘数据…</section>;
  if (!onboarding.ready) return <section className="live-paper-game live-paper-game--error"><AlertTriangle size={20} /><div><b>昨日真实收盘数据正在准备</b><p>{onboarding.reason ?? "请稍后刷新。"}</p></div></section>;
  const assets = onboarding.assets.filter((asset) => `${asset.display_name}${asset.symbol}${asset.sector}`.includes(query));
  const amount = Object.entries(selected).reduce((sum, [symbol, quantity]) => sum + (onboarding.assets.find((asset) => asset.symbol === symbol)?.close ?? 0) * quantity, 0);
  const submit = () => confirm.mutate({ positions: Object.entries(selected).filter(([, quantity]) => quantity > 0).map(([symbol, quantity]) => ({ symbol, quantity })), idempotency_key: crypto.randomUUID() });
  return <section className="live-paper-game" data-testid="paper-game-onboarding"><div className="live-paper-game__status"><div><Activity size={18} /><b>先用昨日收盘价建立初始持仓</b></div><small>真实收盘日：{onboarding.snapshot_date} · 初始资金 {money(onboarding.initial_cash)}</small></div><article className="live-paper-game__market"><p>选择股票后确认，之后会进入今日的延迟真实行情模拟；确认后刷新不会重置账户。</p><input aria-label="搜索初始股票" placeholder="搜索真实股票名称、代码或行业" value={query} onChange={(event) => setQuery(event.target.value)} /><div className="live-paper-game__asset-list">{assets.slice(0, 40).map((asset) => <label key={asset.symbol}><span><b>{asset.display_name} · {asset.symbol}</b><small>{asset.sector} · 昨收 {money(asset.close)}</small></span><input aria-label={`${asset.display_name}数量`} type="number" min={0} step={100} value={selected[asset.symbol] ?? 0} onChange={(event) => setSelected({ ...selected, [asset.symbol]: Math.max(0, Number(event.target.value) || 0) })} /></label>)}</div><p>股票金额（未含费用）：{money(amount)}</p><button type="button" disabled={confirm.isPending || amount <= 0} onClick={submit}>确认初始持仓，进入今日模拟赛</button>{confirm.error && <p className="live-paper-game__warning">{confirm.error instanceof Error ? confirm.error.message : "建仓失败，请重试"}</p>}</article></section>;
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: "up" | "down" }) { return <div><span>{label}</span><b className={tone ? `is-${tone}` : ""}>{value}</b></div>; }
