import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { stockService, type HistoricalDataPoint } from '../services/stockService';
import { Line } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
} from 'chart.js';
import type { StockData } from '../utils/types';

// Register Chart.js components
ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend
);

interface NewsArticle {
  title: string;
  url: string;
  time_published: string;
  summary: string;
  source: string;
}

interface ChartData {
  labels: string[];
  datasets: Array<{
    label: string;
    data: number[];
    fill: boolean;
    borderColor: string;
    tension: number;
  }>;
}

export const StockDetails: React.FC = () => {
  const { symbol } = useParams<{ symbol: string }>();
  const navigate = useNavigate();
  const [stock, setStock] = useState<StockData | null>(null);
  const [historicalData, setHistoricalData] = useState<ChartData | null>(null);
  const [news, setNews] = useState<NewsArticle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchStockAndHistoricalData = async () => {
      setLoading(true);
      setError(null);
      try {
        if (!symbol) {
          setError('No stock symbol provided.');
          setLoading(false);
          return;
        }

        // Fetch stock details
        const fetchedStock = await stockService.fetchStockDetails(symbol);
        if (!fetchedStock) {
          setError(
            `Could not fetch details for ${symbol}. It might not be a valid symbol or API limit reached.`
          );
          setStock(null);
          setLoading(false);
          return;
        }
        setStock(fetchedStock);

        // Fetch historical data
        const fetchedHistoricalData: HistoricalDataPoint[] = await stockService.fetchHistoricalStockData(symbol);
        
        if (fetchedHistoricalData && fetchedHistoricalData.length > 0) {
          // Sort by date
          const sortedData = [...fetchedHistoricalData].sort(
            (a, b) => new Date(a.date).getTime() - new Date(b.date).getTime()
          );

          const dates = sortedData.map(point => point.date);
          const closingPrices = sortedData.map(point => point.close);

          setHistoricalData({
            labels: dates,
            datasets: [
              {
                label: `${symbol} Closing Price`,
                data: closingPrices,
                fill: false,
                borderColor: 'rgb(75, 192, 192)',
                tension: 0.1,
              },
            ],
          });
        } else {
          console.warn('No historical data found for:', symbol);
          setHistoricalData(null);
        }

        // Fetch news
        const fetchedNews = await stockService.fetchNews(symbol);
        setNews(
          fetchedNews.map(article => ({
            title: article.title,
            url: article.url,
            time_published: article.time_published,
            summary: article.summary,
            source: article.source,
          }))
        );
      } catch (err) {
        console.error('Error fetching stock data:', err);
        setError('Failed to fetch stock data. Please try again later.');
      } finally {
        setLoading(false);
      }
    };

    fetchStockAndHistoricalData();
  }, [symbol]);

  if (loading) {
    return (
      <div style={{ padding: 'var(--spacing-3xl)', textAlign: 'center' }}>
        <span className="spinner"></span>
        <p>Loading stock data...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="container" style={{ paddingTop: 'var(--spacing-3xl)' }}>
        <div className="alert alert-error">{error}</div>
        <button className="btn btn-primary" onClick={() => navigate('/')}>
          Back to Home
        </button>
      </div>
    );
  }

  if (!stock) {
    return (
      <div className="container" style={{ paddingTop: 'var(--spacing-3xl)' }}>
        <div className="alert alert-error">Stock not found or invalid symbol.</div>
        <button className="btn btn-primary" onClick={() => navigate('/')}>
          Back to Home
        </button>
      </div>
    );
  }

  const isPositive = stock.change >= 0;

  const chartOptions = {
    responsive: true,
    plugins: {
      legend: {
        position: 'top' as const,
      },
      title: {
        display: true,
        text: `${stock.symbol} Historical Performance`,
      },
    },
    scales: {
      x: {
        type: 'category' as const,
        title: {
          display: true,
          text: 'Date',
        },
        ticks: {
          autoSkip: true,
          maxTicksLimit: 10,
        },
      },
      y: {
        type: 'linear' as const,
        title: {
          display: true,
          text: 'Price (USD)',
        },
      },
    },
  };

  return (
    <div className="container" style={{ paddingTop: 'var(--spacing-3xl)', paddingBottom: 'var(--spacing-3xl)' }}>
      <button
        className="btn btn-ghost"
        onClick={() => navigate('/')}
        style={{ marginBottom: 'var(--spacing-lg)' }}
      >
        ← Back to Home
      </button>

      <div className="grid grid-2">
        {/* Left Pane: Stock Details and Chart */}
        <div>
          {/* Stock Overview */}
          <div className="card">
            <div className="card-header">
              <h2 className="card-title">{stock.name}</h2>
              <p style={{ margin: 0, color: 'var(--text-secondary)' }}>
                Ticker: <strong>{stock.symbol}</strong>
              </p>
            </div>

            <div className="card-body">
              <div style={{ marginBottom: 'var(--spacing-xl)' }}>
                <div style={{ fontSize: '2.5rem', fontWeight: '700', color: 'var(--text-primary)' }}>
                  ${stock.price.toFixed(2)}
                </div>
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 'var(--spacing-md)',
                    marginTop: 'var(--spacing-md)',
                  }}
                >
                  <span className={`badge ${isPositive ? 'badge-success' : 'badge-error'}`}>
                    {isPositive ? '↑' : '↓'} {Math.abs(stock.change).toFixed(2)} ({stock.changePercent.toFixed(2)}%)
                  </span>
                </div>
              </div>

              <p style={{ color: 'var(--text-secondary)' }}>{stock.description}</p>
            </div>
          </div>

          {/* Stock Statistics */}
          <div className="card" style={{ marginTop: 'var(--spacing-xl)' }}>
            <div className="card-header">
              <h3 className="card-title">Stock Statistics</h3>
            </div>

            <div className="card-body">
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr 1fr',
                  gap: 'var(--spacing-lg)',
                }}
              >
                <div>
                  <p
                    style={{
                      margin: '0 0 var(--spacing-xs) 0',
                      color: 'var(--text-tertiary)',
                      fontSize: '0.875rem',
                      fontWeight: '500',
                      textTransform: 'uppercase',
                    }}
                  >
                    High
                  </p>
                  <p style={{ margin: 0, fontSize: '1.25rem', fontWeight: '600' }}>
                    ${stock.high.toFixed(2)}
                  </p>
                </div>

                <div>
                  <p
                    style={{
                      margin: '0 0 var(--spacing-xs) 0',
                      color: 'var(--text-tertiary)',
                      fontSize: '0.875rem',
                      fontWeight: '500',
                      textTransform: 'uppercase',
                    }}
                  >
                    Low
                  </p>
                  <p style={{ margin: 0, fontSize: '1.25rem', fontWeight: '600' }}>
                    ${stock.low.toFixed(2)}
                  </p>
                </div>

                <div>
                  <p
                    style={{
                      margin: '0 0 var(--spacing-xs) 0',
                      color: 'var(--text-tertiary)',
                      fontSize: '0.875rem',
                      fontWeight: '500',
                      textTransform: 'uppercase',
                    }}
                  >
                    Volume
                  </p>
                  <p style={{ margin: 0, fontSize: '1.25rem', fontWeight: '600' }}>
                    {(stock.volume / 1000000).toFixed(1)}M
                  </p>
                </div>

                <div>
                  <p
                    style={{
                      margin: '0 0 var(--spacing-xs) 0',
                      color: 'var(--text-tertiary)',
                      fontSize: '0.875rem',
                      fontWeight: '500',
                      textTransform: 'uppercase',
                    }}
                  >
                    Market Cap
                  </p>
                  <p style={{ margin: 0, fontSize: '1.25rem', fontWeight: '600' }}>
                    {stock.marketCap}
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* Historical Chart */}
          <div className="card" style={{ marginTop: 'var(--spacing-xl)' }}>
            <div className="card-header">
              <h3 className="card-title">Historical Performance</h3>
            </div>
            <div className="card-body">
              {historicalData ? (
                <Line options={chartOptions} data={historicalData} />
              ) : (
                <p style={{ textAlign: 'center', color: 'var(--text-secondary)' }}>
                  No historical data available.
                </p>
              )}
            </div>
          </div>

          {/* Action Buttons */}
          <div
            style={{
              display: 'flex',
              gap: 'var(--spacing-md)',
              marginTop: 'var(--spacing-2xl)',
            }}
          >
            <button className="btn btn-primary btn-lg">Buy Stock</button>
            <button className="btn btn-secondary btn-lg">Add to Watchlist</button>
          </div>
        </div>

        {/* Right Pane: News */}
        <div>
          <div className="card">
            <div className="card-header">
              <h3 className="card-title">Latest News</h3>
            </div>
            <div className="card-body">
              {news.length > 0 ? (
                news.map((article, index) => (
                  <div
                    key={index}
                    style={{
                      marginBottom: 'var(--spacing-lg)',
                      borderBottom: '1px solid var(--border-color)',
                      paddingBottom: 'var(--spacing-lg)',
                    }}
                  >
                    <a
                      href={article.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{
                        fontWeight: '600',
                        marginBottom: 'var(--spacing-xs)',
                        display: 'block',
                        color: 'var(--text-primary)',
                      }}
                    >
                      {article.title}
                    </a>
                    <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
                      {article.summary.substring(0, 150)}...
                    </p>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)' }}>
                      {new Date(article.time_published).toLocaleString()} - {article.source}
                    </span>
                  </div>
                ))
              ) : (
                <p style={{ textAlign: 'center', color: 'var(--text-secondary)' }}>
                  No news available for {symbol}.
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};