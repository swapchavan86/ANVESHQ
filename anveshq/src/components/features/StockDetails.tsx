"use client";

import { useEffect, useState } from "react";
import { StockQuoteDTO, StockHistoryDTO } from "@/lib/dtos/stock.dto";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { ArrowLeft, Star } from "lucide-react";
import { useWatchlist } from "@/hooks/useWatchlist";
import Image from "next/image";

interface StockDetailsProps {
  symbol: string;
  onBack: () => void;
}

interface NewsArticle {
  uuid: string;
  title: string;
  publisher: string;
  link: string;
  providerPublishTime: number;
  type: string;
  thumbnail?: {
    resolutions: {
      url: string;
      width: number;
      height: number;
      tag: string;
    }[];
  };
}

export default function StockDetails({ symbol, onBack }: StockDetailsProps) {
  const [stock, setStock] = useState<StockQuoteDTO | null>(null);
  const [history, setHistory] = useState<StockHistoryDTO | null>(null);
  const [news, setNews] = useState<NewsArticle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { addToWatchlist, removeFromWatchlist, isInWatchlist } = useWatchlist();

  useEffect(() => {
    if (symbol) {
      const fetchStockData = async () => {
        try {
          setLoading(true);
          const [stockResponse, historyResponse, newsResponse] =
            await Promise.all([
              fetch(`/api/stocks/${symbol}`),
              fetch(`/api/stocks/${symbol}/history`),
              fetch(`/api/news/${symbol}`),
            ]);

          if (!stockResponse.ok) {
            const errorData = await stockResponse.json();
            throw new Error(errorData.error || "Failed to fetch stock data");
          }
          if (!historyResponse.ok) {
            const errorData = await historyResponse.json();
            throw new Error(
              errorData.error || "Failed to fetch stock history"
            );
          }
          if (!newsResponse.ok) {
            const errorData = await newsResponse.json();
            throw new Error(errorData.error || "Failed to fetch news");
          }

          const stockData = await stockResponse.json();
          const historyData = await historyResponse.json();
          const newsData = newsResponse.ok ? await newsResponse.json() : [];

          setStock(stockData);
          setHistory(
            historyData.map((item: any) => ({
              Date: item.Date,
              Close: item.Close,
            }))
          );
          setNews(newsData.slice(0, 5));
        } catch (err: any) {
          setError(err.message);
        } finally {
          setLoading(false);
        }
      };

      fetchStockData();
    }
  }, [symbol]);

  const handleWatchlistToggle = () => {
    if (isInWatchlist(symbol)) {
      removeFromWatchlist(symbol);
    } else {
      addToWatchlist(symbol);
    }
  };

  return (
    <div className="w-full">
      <button
        onClick={onBack}
        className="flex items-center gap-2 mb-4 text-sm font-medium text-gray-600 hover:text-gray-900"
      >
        <ArrowLeft size={16} />
        Back to list
      </button>
      {loading && <div>Loading...</div>}
      {error && <div className="text-red-500">Error: {error}</div>}
      {!loading && !error && stock && (
        <>
          <div className="flex items-center gap-4">
            <h1 className="text-2xl font-bold mb-4">
              {stock.name} ({stock.symbol})
            </h1>
            <Star
              size={24}
              className={`cursor-pointer ${
                isInWatchlist(stock.symbol)
                  ? "text-yellow-400"
                  : "text-gray-300"
              }`}
              fill={isInWatchlist(stock.symbol) ? "currentColor" : "none"}
              onClick={handleWatchlistToggle}
            />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            <div className="md:col-span-2">
              <div className="grid grid-cols-1 gap-4">
                <div className="bg-white p-4 rounded-lg shadow">
                  <h2 className="text-xl font-semibold mb-2">Price Details</h2>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <p className="text-gray-600">Current Price</p>
                      <p className="text-2xl font-bold">
                        ₹{stock.price?.toFixed(2)}
                      </p>
                    </div>
                    <div>
                      <p className="text-gray-600">52-Week Low</p>
                      <p className="text-lg">
                        ₹{stock.low_52_week?.toFixed(2)}
                      </p>
                    </div>
                    <div>
                      <p className="text-gray-600">52-Week High</p>
                      <p className="text-lg">
                        ₹{stock.high_52_week_price?.toFixed(2)}
                      </p>
                    </div>
                  </div>
                </div>
                <div className="bg-white p-4 mt-4 rounded-lg shadow">
                  <h2 className="text-xl font-semibold mb-2">
                    Momentum Chart (Last Year)
                  </h2>
                  <ResponsiveContainer width="100%" height={300}>
                    <LineChart data={history || []}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="Date" />
                      <YAxis />
                      <Tooltip />
                      <Legend />
                      <Line
                        type="monotone"
                        dataKey="Close"
                        stroke="#8884d8"
                        activeDot={{ r: 8 }}
                        name="Closing Price"
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>
            <div className="bg-white p-4 rounded-lg shadow sticky top-0 max-h-[600px] overflow-y-auto">
              <h2 className="text-xl font-semibold mb-4">Related News</h2>
              <div className="space-y-4">
                {news.length > 0 ? (
                  news.map((item) => <NewsCard key={item.uuid} {...item} />)
                ) : (
                  <p>No news available for this stock.</p>
                )}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

const NewsCard = ({ title, publisher, link, thumbnail }: NewsArticle) => (
  <a
    href={link}
    target="_blank"
    rel="noopener noreferrer"
    className="group block p-4 rounded-lg hover:bg-gray-50"
  >
    <div className="flex items-start gap-4">
      {thumbnail && (
        <Image
          src={thumbnail.resolutions[0].url}
          alt={title}
          width={100}
          height={100}
          className="rounded-md object-cover"
        />
      )}
      <div>
        <h3 className="text-md font-semibold text-gray-900 group-hover:underline">
          {title}
        </h3>
        <p className="mt-1 text-xs text-gray-500">{publisher}</p>
      </div>
    </div>
  </a>
);
