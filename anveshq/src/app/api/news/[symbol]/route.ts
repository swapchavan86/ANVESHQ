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
      return NextResponse.json(
        { error: "Stock symbol is required" },
        { status: 400 }
      );
    }

    const response = await fetch(`http://localhost:8000/news/${symbol}`);
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error(`Error fetching news for ${symbol}:`, error);
    return NextResponse.json(
      { error: "Failed to fetch news" },
      { status: 500 }
    );
  }
}
