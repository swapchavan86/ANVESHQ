"use client";

import { useState, useEffect, useCallback } from "react";
import { StockTable } from "@/components/features/StockTable";
import { StockQuoteDTO } from "@/lib/dtos/stock.dto";
import StockDetails from "@/components/features/StockDetails";

export default function RootPage() {
  const [stocks, setStocks] = useState<StockQuoteDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [itemsPerPage, setItemsPerPage] = useState(10);
  const [totalCount, setTotalCount] = useState(0);
  const [detailsSymbol, setDetailsSymbol] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const response = await fetch(
        `/api/momentum?page=${currentPage}&limit=${itemsPerPage}`
      );

      if (!response.ok) {
        throw new Error(
          `HTTP error fetching momentum! status: ${response.status}`
        );
      }

      const result = await response.json(); // API now returns { data, count }
      const momentumData = result.data;
      const totalItems = result.count;

      // Map all fields from momentum_ranks to StockQuoteDTO structure
      const mappedStocks: StockQuoteDTO[] = momentumData.map((item: any) => ({
        id: item.id,
        symbol: item.symbol,
        momentumScore: item.rank_score,
        price: item.current_price,
        last_seen_date: item.last_seen_date,
        low_52_week: item.low_52_week,
        low_52_week_date: item.low_52_week_date,
        high_52_week_price: item.high_52_week_price,
        high_52_week_date: item.high_52_week_date,
        created_at: item.created_at,
        updated_at: item.updated_at,
      }));

      setStocks(mappedStocks);
      setTotalCount(totalItems);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [currentPage, itemsPerPage]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const totalPages = Math.ceil(totalCount / itemsPerPage);

  const handleNextPage = () => {
    if (currentPage < totalPages) {
      setCurrentPage((prev) => prev + 1);
    }
  };

  const handlePrevPage = () => {
    if (currentPage > 1) {
      setCurrentPage((prev) => prev - 1);
    }
  };

  const handleItemsPerPageChange = (newLimit: number) => {
    setItemsPerPage(newLimit);
    setCurrentPage(1); // Reset to first page when items per page changes
  };

  const handleAnalyze = (symbol: string) => {
    setDetailsSymbol(symbol);
  };

  const handleBack = () => {
    setDetailsSymbol(null);
  };

  if (loading) {
    return (
      <div className="relative flex place-items-center">
        <p>Loading momentum data...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="relative flex place-items-center">
        <p className="text-red-500">Error: {error}</p>
      </div>
    );
  }

  if (detailsSymbol) {
    return <StockDetails symbol={detailsSymbol} onBack={handleBack} />;
  }

  return (
    <div className="relative flex place-items-center flex-col">
      <StockTable
        stocks={stocks}
        currentPage={currentPage}
        itemsPerPage={itemsPerPage}
        totalItems={totalCount}
        totalPages={totalPages}
        onNextPage={handleNextPage}
        onPrevPage={handlePrevPage}
        onItemsPerPageChange={handleItemsPerPageChange}
        onAnalyze={handleAnalyze}
      />
    </div>
  );
}