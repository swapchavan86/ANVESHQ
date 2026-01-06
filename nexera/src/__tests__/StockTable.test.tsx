import { render, screen } from '@testing-library/react';
import { StockTable } from '@/components/features/StockTable';
import { StockQuoteDTO } from '@/lib/dtos/stock.dto';

const mockStocks: StockQuoteDTO[] = [
  {
    symbol: 'AAPL',
    name: 'Apple Inc.',
    price: 185.92,
    change: 2.45,
    changePercent: 1.34,
    riskLevel: 'Low',
    rankScore: 88,
    isHighVolume: true,
    isNear52WeekHigh: true,
    lastUpdated: new Date().toISOString(),
  },
];

describe('StockTable', () => {
  it('renders stock data correctly', () => {
    render(<StockTable stocks={mockStocks} />);
    
    expect(screen.getByText('AAPL')).toBeInTheDocument();
    expect(screen.getByText(/\$185\.92/)).toBeInTheDocument();
    expect(screen.getByText(/\+1\.34%/)).toBeInTheDocument();
    expect(screen.getByText('Low')).toBeInTheDocument();
    expect(screen.getByText('88')).toBeInTheDocument();
  });
});