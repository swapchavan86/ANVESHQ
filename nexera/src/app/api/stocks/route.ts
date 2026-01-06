import { YahooPriceAdapter } from "@/lib/adapters/yahoo.adapter";
import { NextResponse } from "next/server";

export async function GET() {
  try {
    const adapter = new YahooPriceAdapter();
    // In a real app, these might come from a user's watchlist or a "trending" service
    const symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA"];
    
    const data = await Promise.all(
      symbols.map(symbol => adapter.getQuote(symbol))
    );
    
    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json({ error: "Failed to fetch market data" }, { status: 500 });
  }
}