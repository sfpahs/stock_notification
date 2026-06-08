import requests
import yfinance as yf
import urllib.parse

COMMON_KOREAN_STOCKS = {
    "삼성전자": {"ticker": "005930.KS", "name": "삼성전자", "exchange": "KOSPI"},
    "삼성": {"ticker": "005930.KS", "name": "삼성전자", "exchange": "KOSPI"},
    "SK하이닉스": {"ticker": "000660.KS", "name": "SK하이닉스", "exchange": "KOSPI"},
    "하이닉스": {"ticker": "000660.KS", "name": "SK하이닉스", "exchange": "KOSPI"},
    "카카오": {"ticker": "035720.KS", "name": "카카오", "exchange": "KOSPI"},
    "네이버": {"ticker": "035420.KS", "name": "NAVER", "exchange": "KOSPI"},
    "NAVER": {"ticker": "035420.KS", "name": "NAVER", "exchange": "KOSPI"},
    "현대차": {"ticker": "005380.KS", "name": "현대자동차", "exchange": "KOSPI"},
    "현대자동차": {"ticker": "005380.KS", "name": "현대자동차", "exchange": "KOSPI"},
    "기아": {"ticker": "000270.KS", "name": "기아", "exchange": "KOSPI"},
    "셀트리온": {"ticker": "068270.KS", "name": "셀트리온", "exchange": "KOSPI"},
    "에코프로": {"ticker": "086520.KQ", "name": "에코프로", "exchange": "KOSDAQ"},
}

def search_stocks(query: str):
    """
    Searches for stocks by name or ticker using Yahoo Finance public search API.
    Provides local mapping fallback for Korean search keywords to avoid Yahoo 400 errors.
    Returns a list of dictionaries with ticker, name, and exchange info.
    """
    if not query or len(query.strip()) < 1:
        return []
    
    q_clean = query.strip().lower()
    
    # 1. Check local mapping for common Korean stocks first (for local testing prototype)
    local_results = []
    for key, val in COMMON_KOREAN_STOCKS.items():
        if q_clean in key.lower():
            # Avoid duplicates if multiple keys match
            if not any(r["ticker"] == val["ticker"] for r in local_results):
                local_results.append({
                    "ticker": val["ticker"],
                    "name": val["name"],
                    "exchange": val["exchange"],
                    "type": "EQUITY"
                })
    
    if local_results:
        return local_results[:10]
        
    # 2. Block direct Hangul queries to Yahoo Finance to avoid 400 Bad Request errors.
    # Yahoo's autocomplete API rejects non-ASCII queries.
    has_korean = any('\uac00' <= char <= '\ud7a3' for char in query)
    if has_korean:
        return []
        
    # 3. Live search via Yahoo Finance for English queries and numeric tickers
    url = "https://query2.finance.yahoo.com/v1/finance/search"
    params = {
        "q": query.strip(),
        "lang": "ko-KR"
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            quotes = data.get("quotes", [])
            results = []
            for q in quotes:
                quote_type = q.get("quoteType", "")
                if quote_type not in ("EQUITY", "ETF"):
                    continue
                
                ticker = q.get("symbol", "")
                name = q.get("longname") or q.get("shortname") or ticker
                exchange = q.get("exchange", "")
                
                if exchange == "KSC":
                    exchange = "KOSPI"
                elif exchange == "KOE":
                    exchange = "KOSDAQ"
                
                results.append({
                    "ticker": ticker,
                    "name": name,
                    "exchange": exchange,
                    "type": quote_type
                })
            return results[:10]
    except Exception as e:
        print(f"Error searching stocks for query '{query}': {e}")
    return []

def fetch_stock_price(ticker: str):
    """
    Fetches the current price of a stock using yfinance (no API key required).
    If KIS integration is preferred in the future, this function can be easily swapped.
    """
    if not ticker:
        return None
        
    try:
        # Standardize ticker formatting (e.g. if domestic ticker is just 6 digits)
        ticker_str = ticker.strip().upper()
        if ticker_str.isdigit() and len(ticker_str) == 6:
            ticker_str = f"{ticker_str}.KS"  # Default to KOSPI
            
        t = yf.Ticker(ticker_str)
        # fast_info is highly efficient and fast
        price = t.fast_info.get('last_price')
        if price is not None and price > 0:
            return float(price)
            
        # Fallback to history if fast_info fails
        hist = t.history(period="1d")
        if not hist.empty:
            return float(hist['Close'].iloc[-1])
            
    except Exception as e:
        print(f"Error fetching price for {ticker}: {e}")
    return None

# --- Future KIS API Placeholder (for easy maintenance) ---
# When deploying to Raspberry Pi, you can easily activate KIS API mode by switching this module.
#
# def fetch_stock_price_kis(ticker: str, appkey: str, appsecret: str):
#     # Implement KIS REST API inquiry-price code here.
#     pass
