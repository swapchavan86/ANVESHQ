import { StockQuoteDTO } from "@/lib/dtos/stock.dto";

export const StockTable = ({ stocks }: { stocks: StockQuoteDTO[] }) => {
  return (
    <div className="bg-white border border-border rounded-xl overflow-hidden shadow-sm">
      <table className="w-full text-left border-collapse">
        <thead>
          <tr className="bg-secondary/50 border-b border-border">
            <th className="px-6 py-4 text-xs font-semibold uppercase tracking-wider text-gray-500">Symbol</th>
            <th className="px-6 py-4 text-xs font-semibold uppercase tracking-wider text-gray-500">Price</th>
            <th className="px-6 py-4 text-xs font-semibold uppercase tracking-wider text-gray-500">Change</th>
            <th className="px-6 py-4 text-xs font-semibold uppercase tracking-wider text-gray-500">Risk Level</th>
            <th className="px-6 py-4 text-xs font-semibold uppercase tracking-wider text-gray-500 text-right">Score</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {stocks.map((stock) => (
            <tr key={stock.symbol} className="hover:bg-secondary/30 transition-colors cursor-pointer">
              <td className="px-6 py-4 font-bold">{stock.symbol}</td>
              <td className="px-6 py-4 font-mono">${stock.price.toFixed(2)}</td>
              <td className={`px-6 py-4 font-medium ${stock.change >= 0 ? 'text-accent-success' : 'text-accent-destructive'}`}>
                {`${stock.change >= 0 ? '+' : ''}${stock.changePercent}%`}
              </td>
              <td className="px-6 py-4">
                <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-bold ${getRiskStyles(stock.riskLevel)}`}>
                  {stock.riskLevel}
                </span>
              </td>
              <td className="px-6 py-4 text-right font-semibold text-gray-700">
                {stock.rankScore}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

function getRiskStyles(level: string) {
  switch (level) {
    case 'Low': return 'bg-accent-success/10 text-accent-success';
    case 'Medium': return 'bg-accent-warning/10 text-accent-warning';
    case 'High': return 'bg-accent-destructive/10 text-accent-destructive';
    default: return 'bg-gray-100 text-gray-600';
  }
}