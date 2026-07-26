export interface CNResearchCandidate {
  ticker: string;
  name: string;
  exchange: "XSHG" | "XSHE";
  assetType: "equity" | "etf";
  frozenResultAvailable?: boolean;
  trainingEligible?: boolean;
  rowCount?: number;
  provider?: string | null;
}

// Versioned fixed research pool used by the zero-budget CN workbench.
// This is a local research catalog, not a claim of complete A-share coverage.
export const CN_RESEARCH_UNIVERSE: CNResearchCandidate[] = [
  { ticker: "600519", name: "贵州茅台", exchange: "XSHG", assetType: "equity" },
  { ticker: "000001", name: "平安银行", exchange: "XSHE", assetType: "equity" },
  { ticker: "300308", name: "中际旭创", exchange: "XSHE", assetType: "equity", frozenResultAvailable: true },
  { ticker: "300502", name: "新易盛", exchange: "XSHE", assetType: "equity", frozenResultAvailable: true },
  { ticker: "002384", name: "东山精密", exchange: "XSHE", assetType: "equity", frozenResultAvailable: true },
  { ticker: "300394", name: "天孚通信", exchange: "XSHE", assetType: "equity", frozenResultAvailable: true },
  { ticker: "300750", name: "宁德时代", exchange: "XSHE", assetType: "equity", frozenResultAvailable: true },
  { ticker: "600036", name: "招商银行", exchange: "XSHG", assetType: "equity" },
  { ticker: "601318", name: "中国平安", exchange: "XSHG", assetType: "equity" },
  { ticker: "600030", name: "中信证券", exchange: "XSHG", assetType: "equity" },
  { ticker: "000858", name: "五粮液", exchange: "XSHE", assetType: "equity" },
  { ticker: "002594", name: "比亚迪", exchange: "XSHE", assetType: "equity" },
  { ticker: "600900", name: "长江电力", exchange: "XSHG", assetType: "equity" },
  { ticker: "601888", name: "中国中免", exchange: "XSHG", assetType: "equity" },
  { ticker: "600276", name: "恒瑞医药", exchange: "XSHG", assetType: "equity" },
  { ticker: "601166", name: "兴业银行", exchange: "XSHG", assetType: "equity" },
  { ticker: "600809", name: "山西汾酒", exchange: "XSHG", assetType: "equity" },
  { ticker: "600660", name: "福耀玻璃", exchange: "XSHG", assetType: "equity" },
  { ticker: "000333", name: "美的集团", exchange: "XSHE", assetType: "equity" },
  { ticker: "002475", name: "立讯精密", exchange: "XSHE", assetType: "equity" },
  { ticker: "600887", name: "伊利股份", exchange: "XSHG", assetType: "equity" },
  { ticker: "601012", name: "隆基绿能", exchange: "XSHG", assetType: "equity" },
  { ticker: "601398", name: "工商银行", exchange: "XSHG", assetType: "equity" },
  { ticker: "601939", name: "建设银行", exchange: "XSHG", assetType: "equity" },
  { ticker: "510050", name: "上证50ETF", exchange: "XSHG", assetType: "etf", frozenResultAvailable: true },
  { ticker: "510300", name: "沪深300ETF", exchange: "XSHG", assetType: "etf", frozenResultAvailable: true },
  { ticker: "510500", name: "中证500ETF", exchange: "XSHG", assetType: "etf", frozenResultAvailable: true },
  { ticker: "159915", name: "创业板ETF", exchange: "XSHE", assetType: "etf", frozenResultAvailable: true },
  { ticker: "512100", name: "中证1000ETF", exchange: "XSHG", assetType: "etf", frozenResultAvailable: true }
];
