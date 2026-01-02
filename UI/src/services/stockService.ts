import type { StockData } from '../utils/types';

// Read configuration from .env
const FINNHUB_API_KEY = import.meta.env.VITE_FINNHUB_API_KEY || '';
const FINNHUB_BASE_URL = import.meta.env.VITE_FINNHUB_BASE_URL || 'https://finnhub.io/api/v1';
const YAHOO_FINANCE_BASE_URL = import.meta.env.VITE_YAHOO_FINANCE_BASE_URL || 'https://query1.finance.yahoo.com';
const CORS_PROXY = import.meta.env.VITE_CORS_PROXY || 'https://cors-anywhere.herokuapp.com';
const RAPID_API_KEY = import.meta.env.VITE_RAPID_API_KEY || '';
const RAPID_API_HOST = import.meta.env.VITE_RAPID_API_HOST || '';

export interface HistoricalDataPoint {
  date: string;
  close: number;
  high: number;
  low: number;
  open: number;
  volume: number;
}

// Fetch from RapidAPI Yahoo Finance (recommended - most reliable)
const _fetchFromRapidAPIYahoo = async (symbol: string): Promise<StockData | null> => {
  try {
    if (!RAPID_API_KEY) {
      console.warn('RapidAPI key not configured');
      return null;
    }

    const response = await fetch(
      `https://yh-finance.p.rapidapi.com/stock/v2/get-summary?symbol=${symbol.toUpperCase()}&region=US`,
      {
        method: 'GET',
        headers: {
          'x-rapidapi-key': RAPID_API_KEY,
          'x-rapidapi-host': RAPID_API_HOST || 'yh-finance.p.rapidapi.com',
        },
      }
    );

    if (!response.ok) {
      console.warn(`RapidAPI Yahoo error for ${symbol}:`, response.status);
      return null;
    }

    const data = await response.json();
    const price = data.price?.regularMarketPrice?.raw;
    const previousClose = data.price?.regularMarketPreviousClose?.raw;

    if (!price) {
      console.warn(`No quote data from RapidAPI for ${symbol}`);
      return null;
    }

    const change = price - previousClose;
    const changePercent = (change / previousClose) * 100;

    return {
      id: symbol,
      symbol: symbol.toUpperCase(),
      name: data.price?.longName || symbol.toUpperCase(),
      price,
      change,
      changePercent,
      high: data.price?.regularMarketDayHigh?.raw || price * 1.02,
      low: data.price?.regularMarketDayLow?.raw || price * 0.98,
      volume: data.price?.regularMarketVolume?.raw || 0,
      marketCap: data.summaryDetail?.marketCap?.longFmt || 'N/A',
      description: data.price?.longName || 'Stock data from Yahoo Finance',
    };
  } catch (error) {
    console.error(`RapidAPI Yahoo fetch error for ${symbol}:`, error);
    return null;
  }
};

// Fetch from Yahoo Finance via CORS proxy
const _fetchFromYahooFinance = async (symbol: string): Promise<StockData | null> => {
  try {
    const encodedSymbol = encodeURIComponent(symbol);
    const url = `${YAHOO_FINANCE_BASE_URL}/v10/finance/quoteSummary/${encodedSymbol}?modules=price,summaryDetail`;
    
    const proxiedUrl = `${CORS_PROXY}/${url}`;
    
    const response = await fetch(proxiedUrl, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
      },
    });

    if (!response.ok) {
      console.warn(`Yahoo Finance API error for ${symbol}:`, response.status);
      return null;
    }

    const data = await response.json();
    const quote = data.quoteSummary?.result?.[0]?.price;
    
    if (!quote || !quote.regularMarketPrice) {
      console.warn(`No quote data from Yahoo Finance for ${symbol}`);
      return null;
    }

    const price = quote.regularMarketPrice?.raw || 0;
    const previousClose = quote.regularMarketPreviousClose?.raw || price;
    const change = price - previousClose;
    const changePercent = previousClose ? (change / previousClose) * 100 : 0;

    return {
      id: symbol,
      symbol: symbol.toUpperCase(),
      name: quote.longName || quote.shortName || symbol.toUpperCase(),
      price,
      change,
      changePercent,
      high: quote.regularMarketDayHigh?.raw || price * 1.02,
      low: quote.regularMarketDayLow?.raw || price * 0.98,
      volume: quote.regularMarketVolume?.raw || 0,
      marketCap: quote.marketCap?.longFmt || 'N/A',
      description: 'Stock data from Yahoo Finance',
    };
  } catch (error) {
    console.error(`Yahoo Finance fetch error for ${symbol}:`, error);
    return null;
  }
};

// Fetch from Finnhub
const _fetchFromFinnhub = async (symbol: string): Promise<StockData | null> => {
  try {
    if (!FINNHUB_API_KEY) {
      console.warn('Finnhub API key not configured');
      return null;
    }

    const quoteResponse = await fetch(
      `${FINNHUB_BASE_URL}/quote?symbol=${symbol.toUpperCase()}&token=${FINNHUB_API_KEY}`
    );

    if (!quoteResponse.ok) {
      console.warn(`Finnhub API error for ${symbol}:`, quoteResponse.status);
      return null;
    }

    const quoteData = await quoteResponse.json();

    if (!quoteData.c) {
      console.warn(`No quote data from Finnhub for ${symbol}`);
      return null;
    }

    const profileResponse = await fetch(
      `${FINNHUB_BASE_URL}/stock/profile2?symbol=${symbol.toUpperCase()}&token=${FINNHUB_API_KEY}`
    );
    const profileData = profileResponse.ok ? await profileResponse.json() : {};

    const change = quoteData.c - quoteData.pc;
    const changePercent = (change / quoteData.pc) * 100;

    return {
      id: symbol,
      symbol: symbol.toUpperCase(),
      name: profileData.name || symbol.toUpperCase(),
      price: quoteData.c,
      change,
      changePercent,
      high: quoteData.h || quoteData.c * 1.02,
      low: quoteData.l || quoteData.c * 0.98,
      volume: quoteData.v || 0,
      marketCap: profileData.marketCapitalization
        ? `$${(profileData.marketCapitalization / 1e9).toFixed(2)}B`
        : 'N/A',
      description: profileData.description || 'No description available',
    };
  } catch (error) {
    console.error(`Finnhub fetch error for ${symbol}:`, error);
    return null;
  }
};

// Fetch historical data from RapidAPI
const _fetchHistoricalFromRapidAPI = async (symbol: string): Promise<HistoricalDataPoint[]> => {
  try {
    if (!RAPID_API_KEY) {
      return [];
    }

    const response = await fetch(
      `https://yh-finance.p.rapidapi.com/stock/v3/get-historical-data?symbol=${symbol.toUpperCase()}&interval=1d&diffantsym=tencent`,
      {
        method: 'GET',
        headers: {
          'x-rapidapi-key': RAPID_API_KEY,
          'x-rapidapi-host': RAPID_API_HOST || 'yh-finance.p.rapidapi.com',
        },
      }
    );

    if (!response.ok) {
      console.warn(`RapidAPI historical error for ${symbol}:`, response.status);
      return [];
    }

    const data = await response.json();
    const prices = data.prices || [];

    return prices
      .slice(0, 60)
      .map((point: any) => ({
        date: new Date(point.date * 1000).toISOString().split('T')[0],
        open: point.open || 0,
        high: point.high || 0,
        low: point.low || 0,
        close: point.close || 0,
        volume: point.volume || 0,
      }));
  } catch (error) {
    console.error(`RapidAPI historical fetch error for ${symbol}:`, error);
    return [];
  }
};

// Search using RapidAPI
const _searchRapidAPI = async (query: string): Promise<any[]> => {
  try {
    if (!RAPID_API_KEY) {
      return [];
    }

    const response = await fetch(
      `https://yh-finance.p.rapidapi.com/auto-complete?q=${encodeURIComponent(query)}&region=US`,
      {
        method: 'GET',
        headers: {
          'x-rapidapi-key': RAPID_API_KEY,
          'x-rapidapi-host': RAPID_API_HOST || 'yh-finance.p.rapidapi.com',
        },
      }
    );

    if (!response.ok) {
      console.warn(`RapidAPI search error:`, response.status);
      return [];
    }

    const data = await response.json();
    return data.quotes || [];
  } catch (error) {
    console.error('RapidAPI search error:', error);
    return [];
  }
};

// Search stocks using Finnhub
const _searchFinnhub = async (query: string): Promise<any[]> => {
  try {
    if (!FINNHUB_API_KEY) {
      return [];
    }

    const response = await fetch(
      `${FINNHUB_BASE_URL}/search?q=${encodeURIComponent(query)}&token=${FINNHUB_API_KEY}`
    );

    if (!response.ok) {
      console.warn(`Finnhub search error:`, response.status);
      return [];
    }

    const data = await response.json();
    return data.result || [];
  } catch (error) {
    console.error('Finnhub search error:', error);
    return [];
  }
};

export const stockService = {
  async fetchStockDetails(symbol: string): Promise<StockData | null> {
    try {
      if (!symbol || symbol.trim().length === 0) {
        console.error('Stock symbol is required');
        return null;
      }

      // Try RapidAPI Yahoo Finance first (most reliable)
      if (RAPID_API_KEY) {
        const rapidResult = await _fetchFromRapidAPIYahoo(symbol);
        if (rapidResult) return rapidResult;
      }

      // Try Finnhub
      const finnhubResult = await _fetchFromFinnhub(symbol);
      if (finnhubResult) return finnhubResult;

      // Try Yahoo Finance via CORS proxy (slower, fallback)
      const yahooResult = await _fetchFromYahooFinance(symbol);
      if (yahooResult) return yahooResult;

      console.error(`Could not fetch stock details for ${symbol} from any API`);
      return null;
    } catch (error) {
      console.error(`Error fetching stock details for ${symbol}:`, error);
      return null;
    }
  },

  async fetchHistoricalStockData(symbol: string): Promise<HistoricalDataPoint[]> {
    try {
      if (!symbol || symbol.trim().length === 0) {
        console.error('Stock symbol is required');
        return [];
      }

      // Try RapidAPI first
      if (RAPID_API_KEY) {
        const rapidData = await _fetchHistoricalFromRapidAPI(symbol);
        if (rapidData.length > 0) return rapidData;
      }

      console.warn(`No historical data found for ${symbol}`);
      return [];
    } catch (error) {
      console.error(`Error fetching historical data for ${symbol}:`, error);
      return [];
    }
  },

async searchStocks(query: string): Promise<any[]> { // Changed to any[] for flexibility, adjust to SearchResult[] if defined
    // Make sure your proxy URL is correct and still active
    const proxyUrl = 'https://cors-anywhere.herokuapp.com/';
    const yahooFinanceUrl = `https://query1.finance.yahoo.com/v10/finance/quoteSummary/${query.toUpperCase()}?modules=price,summaryDetail`; // Ensure query is uppercase

    try {
      console.log(`Attempting to fetch stock data for: ${query} via ${proxyUrl}`);
      const response = await fetch(proxyUrl + yahooFinanceUrl);

      if (!response.ok) {
        const errorText = await response.text();
        console.error(`HTTP Error: ${response.status} - ${response.statusText}`);
        console.error('Response body from Yahoo/Proxy:', errorText);

        if (response.status === 403) {
          console.warn('Yahoo Finance API returned 403 Forbidden. This often means the API is blocking requests due to rate limiting or proxy detection. Consider using a dedicated stock API or a backend proxy.');
          throw new Error('Stock data currently unavailable. The external API is restricting access. Please try again later.');
        }

        throw new Error(`Failed to fetch stock data: ${response.statusText}`);
      }

      const data = await response.json();
      console.log('Successfully fetched stock data:', data);

      // --- Example parsing logic for Yahoo Finance data ---
      const result = data?.quoteSummary?.result?.[0];
      if (result && result.price) {
        return [{
          symbol: result.price.symbol,
          description: result.price.longName || result.price.shortName || 'N/A',
          type: result.price.quoteType || 'N/A',
          exchange: result.price.exchangeName || 'N/A',
        }];
      } else if (result && result.error) {
          console.error('Yahoo Finance API returned an error in the data:', result.error);
          throw new Error(result.error.description || 'Error in stock data.');
      }
      return []; // Return empty array if no results found or parsed

    } catch (error: any) {
      console.error('Error in stockService.searchStocks:', error.message);
      // Re-throw the error so the calling component (Header) can handle it.
      throw error;
    }
  },

  async fetchNews(symbol: string): Promise<any[]> {
    try {
      if (!symbol || symbol.trim().length === 0) {
        return [];
      }

      // Return empty for now - RapidAPI doesn't have free news endpoint
      console.info('News fetching not available without premium API');
      return [];
    } catch (error) {
      console.error('Error fetching news:', error);
      return [];
    }
  },

  async fetchSectorPerformance(): Promise<any[]> {
    try {
      const indices = ['^GSPC', '^IXIC', '^DJI'];
      const results = [];

      for (const index of indices) {
        const data = await this.fetchStockDetails(index);
        if (data) {
          results.push({
            name: data.name,
            change: data.changePercent,
            symbol: data.symbol,
          });
        }
      }

      return results;
    } catch (error) {
      console.error('Error fetching sector performance:', error);
      return [];
    }
  },
};