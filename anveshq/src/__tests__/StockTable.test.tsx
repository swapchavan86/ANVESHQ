import { render, screen } from '@testing-library/react';
import { StockTable } from '@/components/features/StockTable';
import { StockQuoteDTO } from '@/lib/dtos/stock.dto';
import { date } from 'zod';

const mockStocks: StockQuoteDTO[] = [
  {
    id: 1,
    symbol: 'AAPL',
    price: 185.92,
    momentumScore: 75.50,
    last_seen_date: '2026-01-07',
    low_52_week: 120.00,
    low_52_week_date: '2025-03-15',
    high_52_week_price: 200.00,
    high_52_week_date: '2025-12-01',
  },
];

describe('StockTable', () => {
  it('renders stock data correctly with new columns and currency', () => {
    // Mock pagination props
    const paginationProps = {
      currentPage: 1,
      itemsPerPage: 10,
      totalItems: 1,
      totalPages: 1,
      onNextPage: () => {},
      onPrevPage: () => {},
      onItemsPerPageChange: () => {},
    };

    render(<StockTable stocks={mockStocks} {...paginationProps} />);
    
    expect(screen.getByText('AAPL')).toBeInTheDocument();
    expect(screen.getByText('₹185.92')).toBeInTheDocument();
    expect(screen.getByText('2026-01-07')).toBeInTheDocument();
    expect(screen.getByText('₹120.00')).toBeInTheDocument();
    expect(screen.getByText('2025-03-15')).toBeInTheDocument();
    expect(screen.getByText('₹200.00')).toBeInTheDocument();
    expect(screen.getByText('2025-12-01')).toBeInTheDocument();
    expect(screen.getByText('75.50')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /analyze/i })).toBeInTheDocument();

    // Check headers are present
    expect(screen.getByText('Symbol')).toBeInTheDocument();
    expect(screen.getByText('Price')).toBeInTheDocument();
    expect(screen.getByText('Last Seen Date')).toBeInTheDocument();
    expect(screen.getByText('52-Week Low Price')).toBeInTheDocument();
    expect(screen.getByText('52-Week Low Date')).toBeInTheDocument();
    expect(screen.getByText('52-Week High Price')).toBeInTheDocument();
    expect(screen.getByText('52-Week High Date')).toBeInTheDocument();
    expect(screen.getByText('Momentum Score')).toBeInTheDocument();
    expect(screen.getByText('Analyze')).toBeInTheDocument();
  });
});