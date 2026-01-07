export type RiskLevel = 'Low' | 'Medium' | 'High';

export interface StockQuoteDTO {
  id?: number; // From momentum_ranks
  symbol: string;
  name?: string;
  price?: number; // From momentum_ranks.current_price
  change?: number;
  changePercent?: number;
  riskLevel?: RiskLevel;
  rankScore?: number; // 1-100 (original rankScore, not momentum)
  momentumScore?: number; // From momentum_ranks.rank_score
  isHighVolume?: boolean;
  isNear52WeekHigh?: boolean;
  lastUpdated?: string;
  last_seen_date?: string; // From momentum_ranks
  low_52_week?: number; // From momentum_ranks
  low_52_week_date?: string; // From momentum_ranks
  high_52_week_price?: number; // From momentum_ranks
  high_52_week_date?: string; // From momentum_ranks
  created_at?: string; // From momentum_ranks
  updated_at?: string; // From momentum_ranks
}

export type StockHistoryDTO = { date: string; close: number }[];