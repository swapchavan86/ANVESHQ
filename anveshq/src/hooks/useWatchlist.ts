"use client";

import { useState, useEffect } from "react";

const WATCHLIST_KEY = "anveshq-watchlist";

export function useWatchlist() {
  const [watchlist, setWatchlist] = useState<string[]>([]);

  useEffect(() => {
    try {
      const storedWatchlist = localStorage.getItem(WATCHLIST_KEY);
      if (storedWatchlist) {
        setWatchlist(JSON.parse(storedWatchlist));
      }
    } catch (error) {
      console.error("Failed to load watchlist from local storage", error);
    }
  }, []);

  const addToWatchlist = (symbol: string) => {
    try {
      const newWatchlist = [...watchlist, symbol];
      setWatchlist(newWatchlist);
      localStorage.setItem(WATCHLIST_KEY, JSON.stringify(newWatchlist));
    } catch (error) {
      console.error("Failed to add to watchlist", error);
    }
  };

  const removeFromWatchlist = (symbol: string) => {
    try {
      const newWatchlist = watchlist.filter((item) => item !== symbol);
      setWatchlist(newWatchlist);
      localStorage.setItem(WATCHLIST_KEY, JSON.stringify(newWatchlist));
    } catch (error) {
      console.error("Failed to remove from watchlist", error);
    }
  };

  const isInWatchlist = (symbol: string) => {
    return watchlist.includes(symbol);
  };

  return { watchlist, addToWatchlist, removeFromWatchlist, isInWatchlist };
}
