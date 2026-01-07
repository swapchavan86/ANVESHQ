import { StockQuoteDTO } from "@/lib/dtos/stock.dto";
import {
  ChevronLeft,
  ChevronRight,
  ArrowUp,
  ArrowDown,
  Star,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useWatchlist } from "@/hooks/useWatchlist";

type SortKey = keyof StockQuoteDTO;

interface StockTableProps {
  stocks: StockQuoteDTO[];
  currentPage: number;
  itemsPerPage: number;
  totalItems: number;
  totalPages: number;
  onNextPage: () => void;
  onPrevPage: () => void;
  onItemsPerPageChange: (limit: number) => void;
  onAnalyze: (symbol: string) => void;
  onWatchlistChange?: () => void;
}

export const StockTable = ({
  stocks,
  currentPage,
  itemsPerPage,
  totalItems,
  totalPages,
  onNextPage,
  onPrevPage,
  onItemsPerPageChange,
  onAnalyze,
  onWatchlistChange,
}: StockTableProps) => {
  const [filter, setFilter] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("momentumScore");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");
  const { watchlist, addToWatchlist, removeFromWatchlist, isInWatchlist } =
    useWatchlist();

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDirection(sortDirection === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDirection("asc");
    }
  };

  const sortedStocks = useMemo(() => {
    return [...stocks].sort((a, b) => {
      const aValue = a[sortKey];
      const bValue = b[sortKey];

      if (aValue === undefined || aValue === null) return 1;
      if (bValue === undefined || bValue === null) return -1;

      if (aValue < bValue) {
        return sortDirection === "asc" ? -1 : 1;
      }
      if (aValue > bValue) {
        return sortDirection === "asc" ? 1 : -1;
      }
      return 0;
    });
  }, [stocks, sortKey, sortDirection]);

  const filteredStocks = useMemo(() => {
    return sortedStocks.filter((stock) =>
      stock.symbol.toLowerCase().includes(filter.toLowerCase())
    );
  }, [sortedStocks, filter]);

  const handleWatchlistToggle = (symbol: string) => {
    if (isInWatchlist(symbol)) {
      removeFromWatchlist(symbol);
    } else {
      addToWatchlist(symbol);
    }
    onWatchlistChange?.();
  };

  const SortableHeader = ({
    label,
    sortKey: key,
    className = "",
  }: {
    label: string;
    sortKey: SortKey;
    className?: string;
  }) => (
    <th
      className={`px-4 py-2 text-xs font-semibold uppercase tracking-wider text-gray-500 bg-secondary/50 cursor-pointer ${className}`}
      onClick={() => handleSort(key)}
    >
      <div className="flex items-center justify-center">
        <span>{label}</span>
        {sortKey === key && (
          <span className="ml-1">
            {sortDirection === "asc" ? (
              <ArrowUp size={12} />
            ) : (
              <ArrowDown size={12} />
            )}
          </span>
        )}
      </div>
    </th>
  );

  return (
    <div className="flex flex-col gap-4 w-full">
      <div className="bg-white border border-border rounded-xl overflow-hidden shadow-sm h-[600px] overflow-y-auto relative">
        <table className="w-full text-left border-separate border-spacing-0 min-w-max">
          <thead className="sticky top-0 z-10">
            <tr className="bg-secondary/50 border-b border-border">
              <th
                rowSpan={2}
                className="px-4 py-2 text-xs font-semibold uppercase tracking-wider text-gray-500 bg-secondary/50 align-middle"
              >
                <Star size={16} className="mx-auto" />
              </th>
              <th
                rowSpan={2}
                className="px-4 py-2 text-xs font-semibold uppercase tracking-wider text-gray-500 bg-secondary/50 align-middle"
              >
                <input
                  type="text"
                  placeholder="Symbol"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                  className="px-2 py-1 border border-gray-300 rounded-md shadow-sm text-sm w-full"
                />
              </th>
              <th
                rowSpan={2}
                className="px-4 py-2 text-xs font-semibold uppercase tracking-wider text-gray-500 bg-secondary/50 align-middle cursor-pointer"
                onClick={() => handleSort("price")}
              >
                <div className="flex items-center justify-center">
                  <span>Price</span>
                  {sortKey === "price" && (
                    <span className="ml-1">
                      {sortDirection === "asc" ? (
                        <ArrowUp size={12} />
                      ) : (
                        <ArrowDown size={12} />
                      )}
                    </span>
                  )}
                </div>
              </th>
              <th
                rowSpan={2}
                className="px-4 py-2 text-xs font-semibold uppercase tracking-wider text-gray-500 bg-secondary/50 align-middle cursor-pointer"
                onClick={() => handleSort("last_seen_date")}
              >
                <div className="flex items-center justify-center">
                  <span>Last Seen</span>
                  {sortKey === "last_seen_date" && (
                    <span className="ml-1">
                      {sortDirection === "asc" ? (
                        <ArrowUp size={12} />
                      ) : (
                        <ArrowDown size={12} />
                      )}
                    </span>
                  )}
                </div>
              </th>
              <th
                colSpan={2}
                className="px-4 py-2 text-xs font-semibold uppercase tracking-wider text-gray-500 bg-secondary/50 text-center"
              >
                52-Week Price
              </th>
              <th
                colSpan={2}
                className="px-4 py-2 text-xs font-semibold uppercase tracking-wider text-gray-500 bg-secondary/50 text-center"
              >
                52-Week Date
              </th>
              <th
                rowSpan={2}
                className="px-4 py-2 text-xs font-semibold uppercase tracking-wider text-gray-500 bg-secondary/50 align-middle cursor-pointer text-right"
                onClick={() => handleSort("momentumScore")}
              >
                <div className="flex items-center justify-end">
                  <span>Momentum Score</span>
                  {sortKey === "momentumScore" && (
                    <span className="ml-1">
                      {sortDirection === "asc" ? (
                        <ArrowUp size={12} />
                      ) : (
                        <ArrowDown size={12} />
                      )}
                    </span>
                  )}
                </div>
              </th>
              <th
                rowSpan={2}
                className="px-4 py-2 text-xs font-semibold uppercase tracking-wider text-gray-500 bg-secondary/50 align-middle text-center"
              >
                Analyze
              </th>
            </tr>
            <tr className="bg-secondary/50 border-b border-border">
              <SortableHeader label="Low" sortKey="low_52_week" />
              <SortableHeader label="High" sortKey="high_52_week_price" />
              <SortableHeader label="Low" sortKey="low_52_week_date" />
              <SortableHeader label="High" sortKey="high_52_week_date" />
            </tr>
          </thead>
          <tbody className="divide-y divide-border text-sm">
            {filteredStocks.map((stock) => (
              <tr
                key={stock.symbol}
                className="hover:bg-secondary/30 transition-colors"
              >
                <td className="px-4 py-2 text-center">
                  <Star
                    size={16}
                    className={`cursor-pointer ${
                      isInWatchlist(stock.symbol)
                        ? "text-yellow-400"
                        : "text-gray-300"
                    }`}
                    fill={
                      isInWatchlist(stock.symbol) ? "currentColor" : "none"
                    }
                    onClick={() => handleWatchlistToggle(stock.symbol)}
                  />
                </td>
                <td className="px-4 py-2 font-bold">{stock.symbol}</td>
                <td className="px-4 py-2 font-mono">
                  {stock.price !== undefined
                    ? `₹${stock.price.toFixed(2)}`
                    : "N/A"}
                </td>
                <td className="px-4 py-2">{stock.last_seen_date || "N/A"}</td>
                <td className="px-4 py-2 text-center">
                  {stock.low_52_week !== undefined
                    ? `₹${stock.low_52_week.toFixed(2)}`
                    : "N/A"}
                </td>
                <td className="px-4 py-2 text-center">
                  {stock.high_52_week_price !== undefined
                    ? `₹${stock.high_52_week_price.toFixed(2)}`
                    : "N/A"}
                </td>
                <td className="px-4 py-2 text-center">
                  {stock.low_52_week_date || "N/A"}
                </td>
                <td className="px-4 py-2 text-center">
                  {stock.high_52_week_date || "N/A"}
                </td>
                <td className="px-4 py-2 text-right font-semibold text-gray-700">
                  {stock.momentumScore !== undefined
                    ? stock.momentumScore.toFixed(0)
                    : "N/A"}
                </td>
                <td className="px-4 py-2 text-center">
                  <button
                    onClick={() => onAnalyze(stock.symbol)}
                    className="inline-flex items-center px-3 py-1.5 border border-transparent text-xs font-medium rounded-md shadow-sm text-white bg-accent-success hover:bg-accent-success/90 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-accent-success"
                  >
                    Analyze
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination Controls */}
      <div className="flex justify-between items-center px-4 py-3 bg-white border border-border rounded-xl shadow-sm">
        <div className="flex items-center gap-2 text-sm text-gray-600">
          <span>Show</span>
          <select
            value={itemsPerPage}
            onChange={(e) => onItemsPerPageChange(Number(e.target.value))}
            className="border border-gray-300 rounded-md shadow-sm py-1 pl-2 pr-7 text-sm font-medium focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary"
          >
            <option value={10}>10</option>
            <option value={50}>50</option>
            <option value={100}>100</option>
          </select>
          <span>entries</span>
        </div>
        <div className="flex items-center space-x-2">
          <button
            onClick={onPrevPage}
            disabled={currentPage === 1}
            className="p-2 border border-gray-300 rounded-md shadow-sm text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <span className="text-sm font-medium text-gray-700">
            Page {currentPage} of {totalPages}
          </span>
          <button
            onClick={onNextPage}
            disabled={currentPage === totalPages}
            className="p-2 border border-gray-300 rounded-md shadow-sm text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
};

function getRiskStyles(level: string) {
  switch (level) {
    case 'Low': return 'bg-accent-success/10 text-accent-success';
    case 'Medium': return 'bg-accent-warning/10 text-accent-warning';
    case 'High': return 'bg-accent-destructive/10 text-accent-destructive';
    default: return 'bg-gray-100 text-gray-600'; // Default for 'Unknown' or undefined
  }
}
