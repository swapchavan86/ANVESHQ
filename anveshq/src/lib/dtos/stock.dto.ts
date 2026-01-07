export type RiskLevel = 'Low' | 'Medium' | 'High';

export interface StockQuoteDTO {
  symbol: string;
  name: string;
  price: number;
  change: number;
  changePercent: number;
  riskLevel: RiskLevel;
  rankScore: number; // 1-100
  isHighVolume: boolean;
  isNear52WeekHigh: boolean;
  lastUpdated: string;
}

export type StockHistoryDTO = { date: string; close: number }[];