import yfinance from "yfinance";

export class YahooPriceAdapter {
  async getQuote(symbol: string) {
    try {
      const quote = await yfinance.quote(symbol);
      return {
        symbol: quote.symbol,
        current_price: quote.regularMarketPrice,
        rank_score: 0, // Placeholder
        risk_score: 0, // Placeholder
        daily_rank_delta: 0, // Placeholder
      };
    } catch (error) {
      console.error(`Failed to fetch quote for symbol ${symbol}:`, error);
      throw new Error(`Failed to fetch quote for symbol ${symbol}`);
    }
  }
}
