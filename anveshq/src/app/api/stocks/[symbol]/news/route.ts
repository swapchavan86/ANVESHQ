import { NewsApiAdapter } from "@/lib/adapters/newsapi.adapter";
import { NextRequest, NextResponse } from "next/server";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ symbol: string }> }
) {
  let symbol: string | undefined = undefined;
  try {
    const params = await context.params;
    symbol = params.symbol;
    if (!symbol) {
      return NextResponse.json({ error: "Stock symbol is required" }, { status: 400 });
    }

    const adapter = new NewsApiAdapter();
    // In a real app, you might want to search for the company name instead of the symbol
    const data = await adapter.getNews(symbol);

    if (!data) {
      return NextResponse.json({ error: "News not found" }, { status: 404 });
    }

    return NextResponse.json(data);
  } catch (error) {
    console.error(`Error fetching news for ${symbol}:`, error);
    return NextResponse.json({ error: "Failed to fetch news" }, { status: 500 });
  }
}
