"use client";

import { useState, useEffect, Suspense } from "react";
import StockDetails from "@/components/features/StockDetails";

interface TopMover {
  symbol: string;
  ltp: number;
  pChange: number;
  netPrice: number;
}

interface MarketNews {
  headline: string;
  summary: string;
  source: string;
  url: string;
}

function MarketOverviewPageContent() {
  const [gainers, setGainers] = useState<TopMover[]>([]);
  const [losers, setLosers] = useState<TopMover[]>([]);
  const [news, setNews] = useState<MarketNews[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detailsSymbol, setDetailsSymbol] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        setError(null);
        const [gainersRes, losersRes, newsRes] = await Promise.all([
          fetch("http://localhost:8000/top-gainers"),
          fetch("http://localhost:8000/top-losers"),
          fetch("http://localhost:8000/market-news"),
        ]);

        if (!gainersRes.ok) throw new Error("Failed to fetch top gainers");
        if (!losersRes.ok) throw new Error("Failed to fetch top losers");
        if (!newsRes.ok) throw new Error("Failed to fetch market news");

        const gainersData = await gainersRes.json();
        const losersData = await losersRes.json();
        console.log("Gainers:", JSON.stringify(gainersData, null, 2));
        console.log("Losers:", JSON.stringify(losersData, null, 2));

        setGainers(gainersData);
        setLosers(losersData);
        setNews(await newsRes.json());
      } catch (e: any) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  const handleAnalyze = (symbol: string) => {
    setDetailsSymbol(symbol);
  };

  const handleBack = () => {
    setDetailsSymbol(null);
  };

  if (detailsSymbol) {
    return <StockDetails symbol={detailsSymbol} onBack={handleBack} />;
  }

  if (loading) {
    return <p>Loading market overview...</p>;
  }

  if (error) {
    return <p className="text-red-500">Error: {error}</p>;
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
      <div className="md:col-span-2">
        <h2 className="text-2xl font-bold mb-4">Market News</h2>
        <div className="space-y-4">
          {news.map((item, index) => (
            <MarketNewsCard key={index} {...item} />
          ))}
        </div>
      </div>
      <div className="space-y-8">
        <TopMoversCard title="Top Gainers" movers={gainers} onAnalyze={handleAnalyze} />
        <TopMoversCard title="Top Losers" movers={losers} onAnalyze={handleAnalyze} />
      </div>
    </div>
  );
}

const TopMoversCard = ({ title, movers, onAnalyze }: { title: string; movers: TopMover[], onAnalyze: (symbol: string) => void }) => (
  <div className="bg-white p-4 rounded-lg shadow">
    <h3 className="text-lg font-semibold mb-2">{title}</h3>
    <ul>
      {movers && movers.length > 0 ? (
        movers.map((mover) => (
          <li
            key={mover.symbol}
            className="flex justify-between items-center py-2 border-b last:border-none"
          >
            <div>
              <span
                className="font-bold cursor-pointer hover:underline"
                onClick={() => onAnalyze(mover.symbol)}
              >
                {mover.symbol}
              </span>
              <span className="text-sm text-gray-500 ml-2">
                ₹{(mover.ltp || 0).toFixed(2)}
              </span>
            </div>
            <span
              className={`font-semibold ${
                (mover.pChange || 0) >= 0 ? "text-green-600" : "text-red-600"
              }`}
            >
              {(mover.pChange || 0).toFixed(2)}%
            </span>
          </li>
        ))
      ) : (
        <p>No data available.</p>
      )}
    </ul>
  </div>
);

const MarketNewsCard = ({ headline, summary, source, url }: MarketNews) => (
  <div className="bg-white p-4 rounded-lg shadow">
    <a href={url} target="_blank" rel="noopener noreferrer" className="text-lg font-semibold text-gray-900 hover:underline">
      {headline}
    </a>
    <p className="mt-1 text-sm text-gray-600">{summary}</p>
    <p className="mt-2 text-xs text-gray-400">{source}</p>
  </div>
);


export default function MarketOverviewPage() {
  return (
    <Suspense fallback={<div>Loading...</div>}>
      <MarketOverviewPageContent />
    </Suspense>
  );
}