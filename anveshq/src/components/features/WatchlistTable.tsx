"use client";

import { StockQuoteDTO } from "@/lib/dtos/stock.dto";
import { useWatchlist } from "@/hooks/useWatchlist";
import { X } from "lucide-react";

interface WatchlistTableProps {
  stocks: StockQuoteDTO[];
  onAnalyze: (symbol: string) => void;
  onWatchlistChange: () => void;
}

export default function WatchlistTable({
  stocks,
  onAnalyze,
  onWatchlistChange,
}: WatchlistTableProps) {
  const { removeFromWatchlist } = useWatchlist();

  const handleRemove = (symbol: string) => {
    removeFromWatchlist(symbol);
    onWatchlistChange();
  };

  return (
    <div className="bg-white border border-border rounded-xl overflow-hidden shadow-sm">
      <table className="w-full text-left border-collapse">
        <thead>
          <tr className="bg-secondary/50 border-b border-border">
            <th className="px-6 py-4 text-xs font-semibold uppercase tracking-wider text-gray-500">
              Symbol
            </th>
            <th className="px-6 py-4 text-xs font-semibold uppercase tracking-wider text-gray-500">
              Price
            </th>
            <th className="px-6 py-4 text-xs font-semibold uppercase tracking-wider text-gray-500">
              Change
            </th>
            <th className="px-6 py-4 text-xs font-semibold uppercase tracking-wider text-gray-500 text-right">
              Momentum Score
            </th>
            <th className="px-6 py-4 text-xs font-semibold uppercase tracking-wider text-gray-500 text-center">
              Analyze
            </th>
            <th className="px-6 py-4 text-xs font-semibold uppercase tracking-wider text-gray-500 text-center">
              Remove
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {stocks.map((stock) => (
            <tr
              key={stock.symbol}
              className="hover:bg-secondary/30 transition-colors"
            >
              <td className="px-6 py-4 font-bold">{stock.symbol}</td>
              <td className="px-6 py-4 font-mono">
                {stock.price !== undefined ? `₹${stock.price.toFixed(2)}` : "N/A"}
              </td>
              <td
                className={`px-6 py-4 font-mono ${
                  (stock.change ?? 0) >= 0
                    ? "text-green-600"
                    : "text-red-600"
                }`}
              >
                {stock.change !== undefined
                  ? `${stock.change.toFixed(2)} (${stock.changePercent?.toFixed(
                      2
                    )}%)`
                  : "N/A"}
              </td>
              <td className="px-6 py-4 text-right font-semibold text-gray-700">
                {stock.momentumScore !== undefined
                  ? stock.momentumScore.toFixed(0)
                  : "N/A"}
              </td>
              <td className="px-6 py-4 text-center">
                <button
                  onClick={() => onAnalyze(stock.symbol)}
                  className="inline-flex items-center px-3 py-1.5 border border-transparent text-xs font-medium rounded-md shadow-sm text-white bg-accent-success hover:bg-accent-success/90 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-accent-success"
                >
                  Analyze
                </button>
              </td>
              <td className="px-6 py-4 text-center">
                <button
                  onClick={() => handleRemove(stock.symbol)}
                  className="p-2 text-gray-400 hover:text-red-600"
                >
                  <X size={16} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
