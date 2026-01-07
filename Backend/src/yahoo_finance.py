from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
from nsetools import Nse

app = FastAPI()
nse = Nse()

# Allow CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/quote/{symbol}")
async def get_quote(symbol: str):
    ticker = yf.Ticker(symbol)
    info = ticker.info
    return {
        "symbol": symbol,
        "name": info.get("shortName", symbol),
        "price": info.get("regularMarketPrice"),
        "change": info.get("regularMarketChange"),
        "changePercent": info.get("regularMarketChangePercent"),
        "low_52_week": info.get("fiftyTwoWeekLow"),
        "high_52_week_price": info.get("fiftyTwoWeekHigh"),
    }

@app.get("/history/{symbol}")
async def get_history(symbol: str):
    ticker = yf.Ticker(symbol)
    hist = ticker.history(period="1y")
    hist = hist.reset_index()
    hist = hist[["Date", "Close"]]
    hist["Date"] = hist["Date"].dt.strftime('%Y-%m-%d')
    return hist.to_dict(orient="records")

@app.get("/top-gainers")
async def get_top_gainers():
    try:
        return nse.get_top_gainers()
    except Exception as e:
        return {"error": str(e)}

@app.get("/top-losers")
async def get_top_losers():
    try:
        return nse.get_top_losers()
    except Exception as e:
        return {"error": str(e)}

@app.get("/market-news")
async def get_market_news():
    # For now, returning mock data.
    # In a real application, this would fetch news from a reliable source.
    return [
        {
            "headline": "Market Hits Record Highs Amidst Strong Economic Data",
            "summary": "The stock market surged to new all-time highs on Tuesday, driven by strong economic data and positive corporate earnings reports.",
            "source": "Reuters",
            "url": "#",
        },
        {
            "headline": "Tech Stocks Lead the Rally as Chipmakers Soar",
            "summary": "Technology stocks were the top performers, with the semiconductor sector seeing significant gains after a major chipmaker announced a breakthrough in its manufacturing process.",
            "source": "Bloomberg",
            "url": "#",
        },
        {
            "headline": "Inflation Concerns Ease as CPI Data Comes in Softer Than Expected",
            "summary": "Investors breathed a sigh of relief as the latest Consumer Price Index (CPI) data showed a smaller-than-expected increase in inflation, easing concerns about potential interest rate hikes.",
            "source": "The Wall Street Journal",
            "url": "#",
        },
        {
            "headline": "Oil Prices Fall on a Surprise Build in Crude Inventories",
            "summary": "Oil prices dropped sharply after the Energy Information Administration (EIA) reported a surprise build in crude oil inventories, signaling weaker demand.",
            "source": "CNBC",
            "url": "#",
        },
        {
            "headline": "Central Bank Signals a Cautious Approach to Monetary Policy",
            "summary": "In its latest meeting, the central bank indicated that it would take a cautious and data-dependent approach to any future changes in monetary policy.",
            "source": "Financial Times",
            "url": "#",
        },
    ]


@app.get("/news/{symbol}")
async def get_news(symbol: str):
    try:
        ticker = yf.Ticker(symbol)
        return ticker.news
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
