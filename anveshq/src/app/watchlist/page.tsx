"use client";

import { useState, useEffect, useCallback, Suspense } from "react";
import { useWatchlist } from "@/hooks/useWatchlist";
import { StockQuoteDTO } from "@/lib/dtos/stock.dto";
import WatchlistTable from "@/components/features/WatchlistTable";
import StockDetails from "@/components/features/StockDetails";

function WatchlistPageContent() {
  const { watchlist } = useWatchlist();
  const [stocks, setStocks] = useState<StockQuoteDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detailsSymbol, setDetailsSymbol] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    if (watchlist.length === 0) {
      setStocks([]);
      setLoading(false);
      return;
    }

    try {
      setLoading(true);
      setError(null);
      const responses = await Promise.all(
        watchlist.map((symbol) => fetch(`/api/stocks/${symbol}`))
      );
      const data = await Promise.all(
        responses.map((res) => {
          if (!res.ok) {
            throw new Error(`Failed to fetch data for a stock in your watchlist.`);
          }
          return res.json();
        })
      );
      setStocks(data);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [watchlist]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleAnalyze = (symbol: string) => {
    setDetailsSymbol(symbol);
  };

  const handleBack = () => {
    setDetailsSymbol(null);
  };

  const handleWatchlistChange = () => {
    fetchData();
  };

  if (detailsSymbol) {
    return <StockDetails symbol={detailsSymbol} onBack={handleBack} />;
  }
  
  if (loading) {
    return <p>Loading watchlist...</p>;
  }

  if (error) {
    return <p className="text-red-500">Error: {error}</p>;
  }

  if (stocks.length === 0) {
    return <p>Your watchlist is empty.</p>;
  }

  return (
    <WatchlistTable
      stocks={stocks}
      onAnalyze={handleAnalyze}
      onWatchlistChange={handleWatchlistChange}
    />
  );
}

export default function WatchlistPage() {
  return (
    <Suspense fallback={<div>Loading...</div>}>
      <WatchlistPageContent />
    </Suspense>
  );
}