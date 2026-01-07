import { NextRequest, NextResponse } from "next/server";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ symbol: string }> }
) {
  const { symbol } = await context.params;
  const response = await fetch(`http://localhost:8000/history/${symbol}`);
  const data = await response.json();
  return NextResponse.json(data);
}
