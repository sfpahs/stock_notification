import asyncio
import datetime
import os
import requests
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import database
import stock_api
from config import BASE_DIR

app = FastAPI(title="주식 목표가 알림 서비스")

# Initialize database tables and insert sample rows
database.init_db()

# Pydantic schemas for request validation
class AlertCreate(BaseModel):
    ticker: str
    name: str
    condition: str
    target_price: float
    enabled: int = 1

class AlertUpdate(BaseModel):
    ticker: str
    name: str
    condition: str
    target_price: float
    enabled: int

class SettingsUpdate(BaseModel):
    telegram_token: str
    telegram_chat_id: str
    check_interval: int

class TelegramTest(BaseModel):
    telegram_token: str
    telegram_chat_id: str

# Helper to send telegram message
def send_telegram(token: str, chat_id: str, message: str):
    if not token or not chat_id:
        return False, "Credentials missing"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        r = requests.post(url, json=payload, timeout=5)
        if r.status_code == 200:
            return True, "Success"
        return False, r.text
    except Exception as e:
        return False, str(e)

# --- Background Task: Async Price Monitor Loop ---
async def price_monitor_loop():
    print("Background price monitor loop started.")
    await asyncio.sleep(5)  # Wait for uvicorn to fully spin up
    
    while True:
        try:
            # 1. Fetch latest settings
            settings = database.get_settings()
            token = settings.get("telegram_token", "")
            chat_id = settings.get("telegram_chat_id", "")
            interval = max(5, settings.get("check_interval", 60)) # Min 5 sec safety limit
            
            # 2. Get active alerts
            alerts = database.list_alerts()
            active_alerts = [a for a in alerts if a["enabled"] == 1]
            
            today_str = datetime.date.today().isoformat()
            
            for alert in active_alerts:
                ticker = alert["ticker"]
                target = alert["target_price"]
                condition = alert["condition"]
                last_date = alert["last_alert_date"]
                alert_id = alert["id"]
                name = alert["name"]
                
                # Skip if already alerted today
                if last_date == today_str:
                    continue
                
                # Fetch price
                price = stock_api.fetch_stock_price(ticker)
                if price is None:
                    print(f"[{ticker}] Failed to fetch price. Skipping.")
                    continue
                
                # Check condition
                triggered = False
                if condition == "<=" and price <= target:
                    triggered = True
                elif condition == ">=" and price >= target:
                    triggered = True
                elif condition == "<" and price < target:
                    triggered = True
                elif condition == ">" and price > target:
                    triggered = True
                
                if triggered:
                    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    msg = f"🔔 *[주식 목표가 도달 알림]*\n\n*종목명:* {name}\n*티커:* `{ticker}`\n*현재가:* {price:,.2f}원\n*조건:* {condition} {target:,.2f}원\n*일시:* {timestamp}"
                    print(f"[{timestamp}] ALERT TRIGGERED: {name} ({ticker}) price {price} meets {condition} {target}")
                    
                    if token and chat_id:
                        success, resp = send_telegram(token, chat_id, msg)
                        if success:
                            database.update_last_alert_date(alert_id, today_str)
                            print(f"[{ticker}] Telegram alert sent successfully.")
                        else:
                            print(f"[{ticker}] Failed to send Telegram: {resp}")
                    else:
                        # For testing mode without API keys, we still trigger the UI state change
                        database.update_last_alert_date(alert_id, today_str)
                        print(f"[{ticker}] (Mock Mode) Alert marked as triggered in UI.")
                
                # Throttling delay to avoid hitting rate limits
                await asyncio.sleep(0.3)
                
        except Exception as e:
            print(f"Error in price_monitor_loop: {e}")
            
        # Re-fetch settings in case interval was updated during the loop run
        try:
            settings = database.get_settings()
            interval = max(5, settings.get("check_interval", 60))
        except:
            interval = 60
            
        await asyncio.sleep(interval)

# Start background monitor loop when app starts
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(price_monitor_loop())

# --- API Endpoints ---

@app.get("/api/settings")
def api_get_settings():
    return database.get_settings()

@app.post("/api/settings")
def api_update_settings(data: SettingsUpdate):
    database.update_settings(data.telegram_token, data.telegram_chat_id, data.check_interval)
    return {"status": "success", "message": "Settings updated successfully."}

@app.post("/api/test-telegram")
def api_test_telegram(data: TelegramTest):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    msg = f"🔔 *[주식 알림 테스트]*\n성공적으로 텔레그램 연동이 설정되었습니다! (송신 시각: {timestamp})"
    success, resp = send_telegram(data.telegram_token, data.telegram_chat_id, msg)
    if success:
        return {"status": "success", "message": "Test message sent successfully."}
    else:
        raise HTTPException(status_code=400, detail=f"Failed to send test message: {resp}")

@app.get("/api/search")
def api_search_stocks(q: str = ""):
    return stock_api.search_stocks(q)

@app.get("/api/alerts")
def api_list_alerts():
    return database.list_alerts()

@app.post("/api/alerts")
def api_create_alert(data: AlertCreate):
    success, error_msg = database.create_alert(
        ticker=data.ticker,
        name=data.name,
        condition=data.condition,
        target_price=data.target_price,
        enabled=data.enabled
    )
    if not success:
        raise HTTPException(status_code=400, detail=error_msg)
    return {"status": "success", "message": f"Alert for '{data.ticker}' created."}

@app.put("/api/alerts/{alert_id}")
def api_update_alert(alert_id: int, data: AlertUpdate):
    success, error_msg = database.update_alert(
        alert_id=alert_id,
        ticker=data.ticker,
        name=data.name,
        condition=data.condition,
        target_price=data.target_price,
        enabled=data.enabled
    )
    if not success:
        raise HTTPException(status_code=400, detail=error_msg)
    return {"status": "success", "message": "Alert updated successfully."}

@app.delete("/api/alerts/{alert_id}")
def api_delete_alert(alert_id: int):
    database.delete_alert(alert_id)
    return {"status": "success", "message": "Alert deleted successfully."}

@app.post("/api/check")
async def api_trigger_check(background_tasks: BackgroundTasks):
    """Allows manual trigger of price check via UI button"""
    # Simply trigger an asynchronous run of price check
    async def run_check_once():
        settings = database.get_settings()
        token = settings.get("telegram_token", "")
        chat_id = settings.get("telegram_chat_id", "")
        alerts = database.list_alerts()
        active_alerts = [a for a in alerts if a["enabled"] == 1]
        today_str = datetime.date.today().isoformat()
        
        for alert in active_alerts:
            # Recheck trigger condition (forces check regardless of last_alert_date for manual trigger)
            ticker = alert["ticker"]
            price = stock_api.fetch_stock_price(ticker)
            if price is not None:
                triggered = False
                if alert["condition"] == "<=" and price <= alert["target_price"]:
                    triggered = True
                elif alert["condition"] == ">=" and price >= alert["target_price"]:
                    triggered = True
                elif alert["condition"] == "<" and price < alert["target_price"]:
                    triggered = True
                elif alert["condition"] == ">" and price > alert["target_price"]:
                    triggered = True
                
                if triggered:
                    msg = f"🔔 *[수동 주가 진단 통과]*\n\n*종목명:* {alert['name']}\n*티커:* `{ticker}`\n*현재가:* {price:,.2f}원\n*조건:* {alert['condition']} {alert['target_price']:,.2f}원"
                    if token and chat_id:
                        send_telegram(token, chat_id, msg)
                        database.update_last_alert_date(alert["id"], today_str)
                    else:
                        database.update_last_alert_date(alert["id"], today_str)
            await asyncio.sleep(0.3)
            
    background_tasks.add_task(run_check_once)
    return {"status": "success", "message": "Manual check queued."}

# Mount static folder and serve index.html for UI
static_dir = BASE_DIR / "static"
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

@app.get("/")
def read_index():
    return FileResponse(static_dir / "index.html")

app.mount("/", StaticFiles(directory=static_dir), name="static")
