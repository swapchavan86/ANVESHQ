"use client";

import useSWR from "swr";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { AlertTriangle, TrendingUp } from "lucide-react";

const fetcher = (url: string) => fetch(url).then((res) => res.json());

export function StockTable() {
  const { data, error } = useSWR("/api/stocks", fetcher);

  if (error) return <div>Failed to load</div>;
  if (!data) return <div>Loading...</div>;

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Symbol</TableHead>
          <TableHead>Price</TableHead>
          <TableHead>Rank</TableHead>
          <TableHead>Risk</TableHead>
          <TableHead>Growth</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.stocks.map((stock: any) => (
          <TableRow key={stock.symbol}>
            <TableCell>{stock.symbol}</TableCell>
            <TableCell>{stock.current_price}</TableCell>
            <TableCell>{stock.rank_score}</TableCell>
            <TableCell>
              <div className="flex items-center">
                <AlertTriangle className="h-4 w-4 text-yellow-500 mr-2" />
                {stock.risk_score}
              </div>
            </TableCell>
            <TableCell>
              <div className="flex items-center">
                <TrendingUp className="h-4 w-4 text-green-500 mr-2" />
                {stock.daily_rank_delta}
              </div>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}