import { YahooPriceAdapter } from "@/lib/adapters/yahoo.adapter";
import { NextResponse } from "next/server";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ symbol: string }> }
) {
  const { symbol } = await params;

  try {
    const adapter = new YahooPriceAdapter();
    const data = await adapter.getQuote(symbol);
    
    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json({ error: `Failed to fetch data for ${symbol}` }, { status: 500 });
  }
}