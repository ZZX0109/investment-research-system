import { ArrowLeft, ArrowRight, Bot, CalendarDays, Clock3, Coins, Newspaper, RotateCcw, Sparkles, Trophy, WalletCards, X } from "lucide-react";
import { useMemo, useState } from "react";
import { useI18n } from "../../i18n";

type Persona = { code: string; name: string; emoji: string; slogan: string; psychology: string; weights: [number, number, number, number] };
type Asset = { id: string; name: string; category: "股票" | "基金" | "黄金"; sector: string; base: number; volatility: number; trend: number; lot: number; seed: number; note: string };
type Order = { id: string; assetId: string; side: "buy" | "sell"; ratio: number; executeDay: number };
type Trade = { id: string; day: number; text: string };

const PERSONAS: Persona[] = [
  { code: "LION", name: "草原狮王", emoji: "🦁", slogan: "看准趋势，气场先到", psychology: "行动果断、容忍波动，但需要警惕过度自信。", weights: [5, 2, 4, 1] },
  { code: "OWL", name: "财报猫头鹰", emoji: "🦉", slogan: "别人看热闹，我看附注", psychology: "重视证据、决策较慢，容易因为等待完美信息错过变化。", weights: [1, 5, 2, 4] },
  { code: "TURTLE", name: "定投海龟", emoji: "🐢", slogan: "慢一点，但别停", psychology: "偏爱规律投入和长期积累，不容易被短期噪声带走。", weights: [1, 4, 1, 5] },
  { code: "FOX", name: "反转狐狸", emoji: "🦊", slogan: "大家都跑，我先看看", psychology: "习惯逆向思考，但也可能为了反对共识而反对共识。", weights: [3, 3, 1, 3] },
  { code: "BEE", name: "分散蜜蜂", emoji: "🐝", slogan: "每朵花一点，风浪小一点", psychology: "非常在意分散风险，接受少赚一点来换取睡得更安稳。", weights: [1, 3, 4, 5] },
  { code: "CHEETAH", name: "动量猎豹", emoji: "🐆", slogan: "风来了，就跟上", psychology: "对价格变化反应快，擅长跟随趋势，也容易追高。", weights: [5, 1, 3, 1] },
  { code: "BEAVER", name: "现金流河狸", emoji: "🦫", slogan: "先把坝修牢，再谈远方", psychology: "先看安全垫和现金流，对讲故事但不赚钱的资产较谨慎。", weights: [1, 5, 3, 5] },
  { code: "DOLPHIN", name: "消息海豚", emoji: "🐬", slogan: "市场有回声，我听得见", psychology: "善于感受市场情绪，但可能把热闹误认为可靠信息。", weights: [4, 2, 5, 2] },
  { code: "CAT", name: "估值橘猫", emoji: "🐈", slogan: "太贵不追，晒会儿太阳", psychology: "在意买入价格和安全边际，但可能长期等待并不存在的低价。", weights: [2, 5, 2, 4] },
  { code: "PENGUIN", name: "共识企鹅", emoji: "🐧", slogan: "队形不能乱，但我会看路", psychology: "相信群体信息，也会通过同伴确认来降低独自决策的不安。", weights: [2, 2, 5, 3] },
  { code: "CAMEL", name: "周期骆驼", emoji: "🐫", slogan: "穿过周期，自带水袋", psychology: "能忍受较长时间的低迷，擅长等待，但有时会过早判断周期反转。", weights: [2, 4, 2, 5] },
  { code: "RACCOON", name: "机会浣熊", emoji: "🦝", slogan: "角落里也可能藏着宝贝", psychology: "喜欢探索冷门机会，小仓位试错能力强，也容易低估小概率风险。", weights: [4, 2, 2, 2] },
];

const QUESTIONS = [
  ["同事说某只股票一周涨了很多，群里都在晒收益。你还没买，最接近你的想法是？", "这个问题观察你面对‘别人赚钱’时，是更容易行动，还是先寻找依据。", "怕再错过，先用一部分钱买进去再说", "先弄清上涨原因和公司情况，不急着跟", "金额不大就试一点，主要是体验", "不熟悉的东西先不碰，错过也能接受"],
  ["你买入后第二天跌了 6%，新闻里没有明确的坏消息。你通常会怎么做？", "短期亏损会放大情绪，真实选择往往和想象不同。", "觉得价格更便宜，马上加一些", "重新检查买入理由，等证据再决定", "先问朋友和看看大家怎么说", "先卖掉，避免损失继续扩大"],
  ["下面四种信息同时出现时，哪一种最容易影响你的决定？", "不同人依赖的信息线索不同，并没有唯一正确答案。", "价格连续上涨、成交明显活跃", "公司收入、利润和现金流正在改善", "很多专业人士给出相似观点", "长期分红稳定、价格波动较小"],
  ["如果一个投资买入后半年几乎没涨，但原本的经营逻辑没有变，你更可能？", "等待能力会影响你能否坚持，也可能让你过度执着。", "换到近期表现更强的资产", "继续核实信息，逻辑没变就再等等", "看别人是否还在持有再决定", "只要风险可控，就按原计划持有"],
  ["你手上有 10 万元闲钱，短期没有明确用途。哪种安排让你最舒服？", "这里关注的是资产配置习惯，而不是哪种收益最高。", "集中在最看好的一个机会", "挑两三项研究清楚的资产", "股票、基金和黄金都放一点", "大部分保留低波动资产，少量尝试"],
  ["某行业突然出现重大政策消息，但具体细则还没公布。你会怎样处理？", "信息不完整时，人们对不确定性的耐受程度差异很大。", "先根据方向行动，细则出来再调整", "等待正式文件并分析实际影响", "观察市场和其他人的第一反应", "不参与这种不确定性较高的机会"],
  ["你持有的资产已经盈利 25%，最近仍在上涨。你最可能怎么做？", "盈利后的决策同样容易受到贪婪、锚定和后悔影响。", "趋势很好，考虑继续增加", "重新判断价格是否仍然合理", "参考同类投资者是否开始卖出", "卖出一部分，把利润先留下来"],
  ["如果只能选一个原因让你晚上睡不着，会是哪一个？", "最难承受的事情，往往比最想获得的收益更能定义风险偏好。", "看好的机会大涨，自己却没有参与", "持仓逻辑讲不清楚，不知道为何涨跌", "自己的选择和大家完全相反", "账户出现超过预期的大幅亏损"],
  ["你第一次接触一个陌生行业，通常会从哪里开始？", "信息收集方式会影响你看到的世界，也会形成不同偏差。", "先看近期走势，理解市场关注点", "读行业资料和代表公司的报告", "找熟悉这个行业的人聊一聊", "先通过宽基或行业基金小额接触"],
  ["市场连续下跌两周，各种消息都很悲观。你认为自己更像下面哪一种？", "压力环境中的行为，比平稳时期的自我评价更真实。", "寻找跌得最狠的反弹机会", "逐项判断哪些资产被错杀", "等市场情绪稳定后再行动", "优先保护现金，暂时减少风险"],
  ["一项投资需要至少三年才可能看到结果，但中间可能波动很大。你会？", "长期并不只意味着时间长，还意味着期间需要承受不确定性。", "如果空间足够大，可以集中参与", "只有证据充分才会耐心等待", "有人一起跟踪会更容易坚持", "采用定期投入，避免一次押注时点"],
  ["朋友向你推荐一个自己赚过钱的方法，但无法解释为什么有效。你会？", "这个情境区分结果导向、证据导向和社会信任。", "成绩不错就值得快速尝试", "无法解释就先不使用", "小额跟随，同时观察后续表现", "只采用自己事先写进计划的方法"],
  ["你发现自己的判断错了，而且已经亏损。下面哪种做法最接近你？", "承认错误涉及沉没成本，也关系到是否能持续修正策略。", "寻找另一个机会尽快赚回来", "明确错误原因后及时调整", "看看其他持有人是否也改变观点", "按预设损失范围执行，不临时发挥"],
  ["如果最终收益相同，你更喜欢哪一种过程？", "最终收益一样时，波动路径仍会明显影响真实体验。", "中间大涨大跌，但充满机会", "波动可以接受，只要原因可解释", "和市场大多数人的体验差不多", "过程平稳，哪怕偶尔少赚一些"],
  ["每天打开投资软件时，你最想先看到什么？", "注意力放在哪里，长期会塑造交易频率和判断方式。", "今天涨跌和热门排行榜", "公司数据与重要公告变化", "大家正在讨论什么", "整体资产配置和风险是否偏离"],
  ["对你来说，投资最像下面哪件事？", "最后一道题用直觉检查前面答案，不需要想得太复杂。", "赛车：判断方向并快速调整", "解谜：不断收集证据接近真相", "组队游戏：交流信息共同判断", "种树：控制节奏，等待时间发挥作用"],
];

const ASSETS: Asset[] = [
  { id: "s-tech-a", name: "科技制造 A", category: "股票", sector: "科技", base: 68, volatility: .042, trend: .0012, lot: 100, seed: 2, note: "成长较快，波动明显" },
  { id: "s-tech-b", name: "云服务 B", category: "股票", sector: "科技", base: 35, volatility: .05, trend: .0016, lot: 100, seed: 7, note: "对产业消息敏感" },
  { id: "s-cons-a", name: "大众消费 A", category: "股票", sector: "消费", base: 92, volatility: .026, trend: .0007, lot: 100, seed: 4, note: "关注需求变化" },
  { id: "s-med-a", name: "医疗创新 A", category: "股票", sector: "医疗", base: 47, volatility: .038, trend: .0009, lot: 100, seed: 10, note: "研发和政策影响较大" },
  { id: "s-energy-a", name: "能源周期 A", category: "股票", sector: "周期", base: 19, volatility: .031, trend: .0004, lot: 100, seed: 13, note: "受商品周期影响" },
  { id: "s-fin-a", name: "稳健金融 A", category: "股票", sector: "金融", base: 12, volatility: .018, trend: .0003, lot: 100, seed: 16, note: "关注利率环境" },
  { id: "f-wide", name: "全市场指数基金", category: "基金", sector: "全市场", base: 3.26, volatility: .014, trend: .0006, lot: 100, seed: 3, note: "分散覆盖多个行业" },
  { id: "f-growth", name: "成长行业基金", category: "基金", sector: "科技", base: 1.84, volatility: .025, trend: .0009, lot: 100, seed: 9, note: "成长板块，波动较高" },
  { id: "f-dividend", name: "稳健红利基金", category: "基金", sector: "红利", base: 2.13, volatility: .011, trend: .00045, lot: 100, seed: 14, note: "偏现金流和股东回报" },
  { id: "g-paper", name: "黄金 ETF", category: "黄金", sector: "黄金", base: 5.7, volatility: .012, trend: .00035, lot: 100, seed: 6, note: "受避险情绪影响" },
  { id: "g-spot", name: "积存金（模拟）", category: "黄金", sector: "黄金", base: 568, volatility: .01, trend: .0003, lot: 1, seed: 12, note: "按克模拟，不含费用" },
];

const EVENTS = [
  { title: "央行释放流动性信号", detail: "市场讨论政策力度，金融和成长板块出现分歧。正式细则尚未完全公布。", mood: 1, sectors: ["金融", "科技"] },
  { title: "科技龙头上调资本开支", detail: "产业链订单预期升温，但市场也开始讨论短期现金流压力。", mood: 2, sectors: ["科技"] },
  { title: "海外市场夜间大幅波动", detail: "避险情绪升高，高波动资产承压，黄金关注度上升。", mood: -2, sectors: ["科技", "黄金"] },
  { title: "大宗商品价格低于预期", detail: "需求恢复速度引发争论，能源与周期板块成交放大。", mood: -1, sectors: ["周期"] },
  { title: "消费数据出现温和改善", detail: "必选消费保持稳定，可选消费的恢复仍存在分歧。", mood: 1, sectors: ["消费"] },
  { title: "医药行业政策公开征求意见", detail: "创新方向获得关注，但落地时间和受益范围仍不确定。", mood: 1, sectors: ["医疗"] },
  { title: "市场连续上涨后成交降温", detail: "指数变化不大，行业之间的表现差异明显扩大。", mood: -1, sectors: ["全市场", "科技"] },
  { title: "避险需求有所回落", detail: "风险偏好恢复，黄金走弱，成长类资产获得更多关注。", mood: 1, sectors: ["黄金", "科技"] },
];

function getPersona(answers: number[]) {
  const dimensions = answers.reduce<[number, number, number, number]>((score, answer, index) => { score[answer] += 1 + (index % 3) * .15; return score; }, [0, 0, 0, 0]);
  const normalized = dimensions.map((value) => value / Math.max(1, answers.length) * 20);
  return PERSONAS.reduce((best, persona) => { const distance = persona.weights.reduce((sum, weight, i) => sum + Math.abs(weight - normalized[i]), 0); return distance < best.distance ? { persona, distance } : best; }, { persona: PERSONAS[0], distance: Infinity }).persona;
}

function assetPrice(asset: Asset, day: number) {
  const event = EVENTS[(day - 1) % EVENTS.length];
  const sectorEffect = event.sectors.includes(asset.sector) ? event.mood * asset.volatility * .34 : 0;
  const safeHaven = asset.category === "黄金" && event.mood < 0 ? Math.abs(event.mood) * .006 : 0;
  const wave = Math.sin((day + asset.seed) * .79) * asset.volatility + Math.cos((day + asset.seed) * .31) * asset.volatility * .45;
  return Math.max(.01, Math.round(asset.base * (1 + asset.trend * day + wave + sectorEffect + safeHaven) * 100) / 100);
}

export function InvestmentPersonalityLab({ onExit }: { onExit: () => void }) {
  const { l } = useI18n();
  const [stage, setStage] = useState<"intro" | "quiz" | "result" | "game">("intro");
  const [question, setQuestion] = useState(0);
  const [answers, setAnswers] = useState<number[]>([]);
  const [day, setDay] = useState(1);
  const [cash, setCash] = useState(100000);
  const [holdings, setHoldings] = useState<Record<string, number>>({});
  const [orders, setOrders] = useState<Order[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [category, setCategory] = useState<Asset["category"]>("股票");
  const [selectedId, setSelectedId] = useState(ASSETS[0].id);
  const [ratio, setRatio] = useState(.25);
  const persona = useMemo(() => getPersona(answers), [answers]);
  const selected = ASSETS.find((asset) => asset.id === selectedId) ?? ASSETS[0];
  const event = EVENTS[(day - 1) % EVENTS.length];
  const marketValue = ASSETS.reduce((sum, asset) => sum + (holdings[asset.id] ?? 0) * assetPrice(asset, day), 0);
  const total = Math.round(cash + marketValue);

  const answer = (choice: number) => { setAnswers((values) => [...values, choice]); if (question === QUESTIONS.length - 1) setStage("result"); else setQuestion((value) => value + 1); };
  const changeCategory = (next: Asset["category"]) => { setCategory(next); setSelectedId(ASSETS.find((asset) => asset.category === next)?.id ?? ASSETS[0].id); };
  const placeOrder = (side: "buy" | "sell") => { if (day >= 30 || (side === "sell" && !(holdings[selected.id] > 0))) return; setOrders((items) => [...items, { id: `${day}-${selected.id}-${side}-${Date.now()}-${items.length}`, assetId: selected.id, side, ratio, executeDay: day + 1 }]); };
  const advanceDay = () => {
    if (day >= 30) return;
    const nextDay = day + 1, due = orders.filter((order) => order.executeDay === nextDay), nextHoldings = { ...holdings }; let nextCash = cash; const nextTrades: Trade[] = [];
    due.forEach((order) => {
      const asset = ASSETS.find((item) => item.id === order.assetId)!; const price = assetPrice(asset, nextDay);
      if (order.side === "buy") {
        const units = Math.floor((nextCash * order.ratio) / price / asset.lot) * asset.lot;
        if (units > 0) { nextCash -= units * price; nextHoldings[asset.id] = (nextHoldings[asset.id] ?? 0) + units; nextTrades.push({ id: order.id, day: nextDay, text: `买入 ${asset.name} ${units} 份，成交价 ¥${price.toFixed(2)}` }); }
        else nextTrades.push({ id: order.id, day: nextDay, text: `${asset.name} 买入未成交：可用现金不足一手` });
      } else {
        const owned = nextHoldings[asset.id] ?? 0; let units = order.ratio >= 1 ? owned : Math.floor(owned * order.ratio / asset.lot) * asset.lot; if (units === 0 && owned >= asset.lot) units = asset.lot;
        if (units > 0) { nextCash += units * price; nextHoldings[asset.id] = owned - units; nextTrades.push({ id: order.id, day: nextDay, text: `卖出 ${asset.name} ${units} 份，成交价 ¥${price.toFixed(2)}` }); }
        else nextTrades.push({ id: order.id, day: nextDay, text: `${asset.name} 卖出未成交：持仓数量不足` });
      }
    });
    setCash(nextCash); setHoldings(nextHoldings); setTrades((items) => [...nextTrades, ...items]); setOrders((items) => items.filter((order) => order.executeDay > nextDay)); setDay(nextDay);
  };
  const reset = () => { setStage("intro"); setQuestion(0); setAnswers([]); setDay(1); setCash(100000); setHoldings({}); setOrders([]); setTrades([]); };

  return <main className="personality-lab" data-testid="investment-personality-lab">
    <section className="personality-lab__hero"><button type="button" className="personality-lab__back" onClick={onExit}><ArrowLeft size={16} />{l("返回研究面板", "Back to research")}</button><div className="personality-lab__hero-copy"><span className="personality-lab__kicker"><Sparkles size={15} /> 投资人格实验室</span><h2>先认识自己的投资习惯，再到历史里生活 30 天</h2><p>16 个贴近日常的选择情境，搭配多资产历史风格回放。虚拟资金、娱乐竞赛，不构成投资建议。</p></div><div className="personality-lab__steps"><span className={stage === "intro" || stage === "quiz" ? "is-active" : ""}>1 · 16题测试</span><span className={stage === "result" ? "is-active" : ""}>2 · 策略画像</span><span className={stage === "game" ? "is-active" : ""}>3 · 30日挑战</span></div></section>

    {stage === "intro" && <section className="personality-lab__intro-card"><div><span className="personality-lab__giant">🧠 × 🧺</span><h3>你如何面对赚钱、亏损、等待和别人的意见？</h3><p>题目没有专业术语，也没有标准答案。每题描述一个真实决策处境，完成约需 4–6 分钟，结果对应 12 种娱乐人格和不同的模拟策略。</p></div><button type="button" className="personality-lab__primary" onClick={() => setStage("quiz")}>开始 16 题测试<ArrowRight size={17} /></button></section>}
    {stage === "quiz" && <section className="personality-lab__quiz"><div className="personality-lab__progress"><span style={{ width: `${((question + 1) / QUESTIONS.length) * 100}%` }} /></div><small>第 {question + 1} 题 / 共 {QUESTIONS.length} 题</small><h3>{QUESTIONS[question][0]}</h3><p className="personality-lab__question-context">{QUESTIONS[question][1]}</p><div className="personality-lab__answers">{QUESTIONS[question].slice(2).map((choice, index) => <button type="button" key={choice} onClick={() => answer(index)}><b>{String.fromCharCode(65 + index)}</b><span>{choice}</span></button>)}</div>{question > 0 && <button type="button" className="personality-lab__quiz-back" onClick={() => { setQuestion((value) => value - 1); setAnswers((values) => values.slice(0, -1)); }}><ArrowLeft size={14} />返回上一题</button>}</section>}
    {stage === "result" && <section className="personality-lab__result"><div className="personality-lab__persona-card"><span>{persona.emoji}</span><small>{persona.code}</small><h3>{persona.name}</h3><blockquote>“{persona.slogan}”</blockquote><p>{persona.psychology}</p></div><div className="personality-lab__result-copy"><span className="personality-lab__kicker">你的模拟策略</span><h3>模型信号 × 行为偏好 × 资产配置</h3><p>挑战会同时提供股票、基金和黄金。你可以分散持仓，也可以观察不同人格机器人如何响应同一组公告。委托不会立刻成交，而是在下一交易日按新价格处理。</p><div className="personality-lab__weights"><span>行动 {persona.weights[0]}/5</span><span>证据 {persona.weights[1]}/5</span><span>共识 {persona.weights[2]}/5</span><span>耐心 {persona.weights[3]}/5</span></div><button type="button" className="personality-lab__primary" onClick={() => setStage("game")}>进入多资产挑战<ArrowRight size={17} /></button></div></section>}

    {stage === "game" && <section className="personality-lab__game"><div className="personality-lab__gamebar"><div><CalendarDays size={18} /><b>第 {day} / 30 日</b><span>历史随机回放 · 所有人同场信息</span></div><div><span>账户总资产</span><strong>¥{total.toLocaleString()}</strong></div></div><div className="personality-lab__game-grid personality-lab__game-grid--market"><article className="personality-lab__bulletin"><span className="personality-lab__kicker"><Newspaper size={15} /> 今日公告</span><h3>{event.title}</h3><p>{event.detail}</p><div className="personality-lab__event-tags">{event.sectors.map((sector) => <span key={sector}>{sector}</span>)}<span>{event.mood > 0 ? "情绪升温" : "风险扰动"}</span><span>当日已公开</span></div><small>只展示今天能够知道的信息。你提交的委托将在下一交易日处理，因此成交价可能变化。</small></article><MarketPanel category={category} selectedId={selected.id} onCategory={changeCategory} onSelect={setSelectedId} day={day} holdings={holdings} /><OrderPanel asset={selected} day={day} cash={cash} holdings={holdings} ratio={ratio} orders={orders} onRatio={setRatio} onOrder={placeOrder} onCancel={(id) => setOrders((items) => items.filter((item) => item.id !== id))} onAdvance={advanceDay} /></div><div className="personality-lab__game-grid personality-lab__game-grid--account"><Portfolio holdings={holdings} cash={cash} day={day} trades={trades} /><Leaderboard day={day} userTotal={total} persona={persona} /></div><button type="button" className="personality-lab__reset" onClick={reset}><RotateCcw size={14} />重新测试并清空模拟账户</button></section>}
  </main>;
}

function MarketPanel({ category, selectedId, onCategory, onSelect, day, holdings }: { category: Asset["category"]; selectedId: string; onCategory: (value: Asset["category"]) => void; onSelect: (id: string) => void; day: number; holdings: Record<string, number> }) {
  return <article className="personality-lab__market"><span className="personality-lab__kicker"><Coins size={15} /> 可选资产</span><div className="personality-lab__category-tabs">{(["股票", "基金", "黄金"] as const).map((item) => <button type="button" key={item} className={category === item ? "is-active" : ""} onClick={() => onCategory(item)}>{item}</button>)}</div><div className="personality-lab__asset-options">{ASSETS.filter((asset) => asset.category === category).map((asset) => { const price = assetPrice(asset, day), previous = assetPrice(asset, Math.max(1, day - 1)), change = (price / previous - 1) * 100; return <button type="button" key={asset.id} className={selectedId === asset.id ? "is-active" : ""} onClick={() => onSelect(asset.id)}><span><b>{asset.name}</b><small>{asset.sector} · {asset.note}</small></span><span><strong>¥{price.toFixed(2)}</strong><em className={change >= 0 ? "is-up" : "is-down"}>{change >= 0 ? "+" : ""}{change.toFixed(2)}%</em>{holdings[asset.id] ? <small>持有 {holdings[asset.id]}</small> : null}</span></button>; })}</div></article>;
}

function OrderPanel({ asset, day, cash, holdings, ratio, orders, onRatio, onOrder, onCancel, onAdvance }: { asset: Asset; day: number; cash: number; holdings: Record<string, number>; ratio: number; orders: Order[]; onRatio: (value: number) => void; onOrder: (side: "buy" | "sell") => void; onCancel: (id: string) => void; onAdvance: () => void }) {
  return <article className="personality-lab__trade"><span className="personality-lab__kicker"><WalletCards size={15} /> 模拟委托</span><div className="personality-lab__quote"><div><small>当前选择</small><b>{asset.name}</b><span>{asset.category} · {asset.sector}</span></div><strong>¥{assetPrice(asset, day).toFixed(2)}</strong></div><dl><div><dt>可用现金</dt><dd>¥{Math.round(cash).toLocaleString()}</dd></div><div><dt>当前持有</dt><dd>{holdings[asset.id] ?? 0} 份</dd></div></dl><label className="personality-lab__ratio"><span>委托比例</span><select value={ratio} onChange={(event) => onRatio(Number(event.target.value))}><option value={.1}>可用资金/持仓的 10%</option><option value={.25}>可用资金/持仓的 25%</option><option value={.5}>可用资金/持仓的 50%</option><option value={1}>可用资金/持仓的 100%</option></select></label><div className="personality-lab__trade-actions"><button type="button" onClick={() => onOrder("buy")} disabled={day === 30}>提交买入</button><button type="button" onClick={() => onOrder("sell")} disabled={day === 30 || !holdings[asset.id]}>提交卖出</button></div><p className="personality-lab__settlement"><Clock3 size={14} />第 {day} 日提交，第 {Math.min(30, day + 1)} 日按模拟开盘价成交；提交后价格仍可能变化。</p>{orders.length > 0 && <div className="personality-lab__pending"><b>待成交委托</b>{orders.map((order) => { const item = ASSETS.find((assetItem) => assetItem.id === order.assetId)!; return <div key={order.id}><span>{order.side === "buy" ? "买入" : "卖出"} · {item.name} · {Math.round(order.ratio * 100)}%</span><button type="button" onClick={() => onCancel(order.id)} aria-label="撤销委托"><X size={13} /></button></div>; })}</div>}<button type="button" className="personality-lab__next" onClick={onAdvance} disabled={day === 30}>{day === 30 ? "30 日挑战完成" : `结束第 ${day} 日，进入下一交易日`}<ArrowRight size={16} /></button></article>;
}

function Portfolio({ holdings, cash, day, trades }: { holdings: Record<string, number>; cash: number; day: number; trades: Trade[] }) {
  const owned = ASSETS.filter((asset) => holdings[asset.id] > 0);
  return <article className="personality-lab__portfolio"><span className="personality-lab__kicker"><WalletCards size={15} /> 我的资产配置</span><div className="personality-lab__allocation"><div><b>现金</b><span>¥{Math.round(cash).toLocaleString()}</span></div>{owned.map((asset) => <div key={asset.id}><b>{asset.name}</b><span>{holdings[asset.id]} 份 · ¥{Math.round(holdings[asset.id] * assetPrice(asset, day)).toLocaleString()}</span></div>)}{owned.length === 0 && <p>暂时没有持仓。你可以跨股票、基金和黄金建立组合。</p>}</div>{trades.length > 0 && <details className="personality-lab__trade-log"><summary>查看成交记录（{trades.length}）</summary>{trades.map((trade) => <p key={trade.id}>第 {trade.day} 日 · {trade.text}</p>)}</details>}</article>;
}

function Leaderboard({ day, userTotal, persona }: { day: number; userTotal: number; persona: Persona }) {
  const rows = PERSONAS.slice(0, 7).map((item, index) => ({ ...item, value: Math.round(100000 * (1 + Math.sin((day + index) * .73) * .018 + day * (.0006 + index * .0001))) })); rows.push({ ...persona, name: `你 · ${persona.name}`, value: userTotal }); rows.sort((a, b) => b.value - a.value);
  return <article className="personality-lab__leaderboard"><span className="personality-lab__kicker"><Trophy size={15} /> 同场人格榜</span><ol>{rows.map((row, index) => <li key={`${row.code}-${row.name}`}><b>{index + 1}</b><span>{row.emoji} {row.name}</span><strong>{((row.value / 100000 - 1) * 100).toFixed(2)}%</strong></li>)}</ol><p><Bot size={14} />人格机器人按各自固定权重配置多类资产；排名仅用于娱乐回放。</p></article>;
}
