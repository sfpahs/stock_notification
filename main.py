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
            
            # 3. Handle Date Change Reset
            # If last_alert_date is from a previous day, reset triggered_state to 0
            for alert in active_alerts:
                if alert["last_alert_date"] != today_str and alert["triggered_state"] != 0:
                    database.update_alert_trigger_state(alert["id"], 0)
                    alert["triggered_state"] = 0  # Sync local list object
            
            # 4. Fetch unique prices to avoid duplicate API calls
            price_cache = {}
            unique_tickers = list(set(a["ticker"] for a in active_alerts))
            for ticker in unique_tickers:
                price = stock_api.fetch_stock_price(ticker)
                price_cache[ticker] = price
                await asyncio.sleep(0.3)  # Throttling
                
            # 5. Evaluate raw condition trigger for each alert
            triggered_alerts = []
            non_triggered_alerts = []
            
            for alert in active_alerts:
                ticker = alert["ticker"]
                price = price_cache.get(ticker)
                
                if price is None:
                    continue
                
                # Raw evaluation
                is_triggered = False
                cond = alert["condition"]
                target = alert["target_price"]
                
                if cond == "<=" and price <= target:
                    is_triggered = True
                elif cond == ">=" and price >= target:
                    is_triggered = True
                elif cond == "<" and price < target:
                    is_triggered = True
                elif cond == ">" and price > target:
                    is_triggered = True
                    
                alert["current_price"] = price  # Store price in alert object
                
                if is_triggered:
                    triggered_alerts.append(alert)
                else:
                    non_triggered_alerts.append(alert)
            
            # 6. Apply Priority (Dominance) Filtering on triggered alerts per ticker
            # For each ticker, if multiple alerts trigger:
            # - Group by condition type
            # - For '<=' (or '<') condition: pick the one with the MINIMUM target price
            # - For '>=' (or '>') condition: pick the one with the MAXIMUM target price
            final_alerts_to_send = []
            
            # Group by ticker
            ticker_groups = {}
            for alert in triggered_alerts:
                ticker = alert["ticker"]
                ticker_groups.setdefault(ticker, []).append(alert)
                
            for ticker, group in ticker_groups.items():
                # Separate into above (>=, >) and below (<=, <)
                below_group = [a for a in group if "<" in a["condition"]]
                above_group = [a for a in group if ">" in a["condition"]]
                
                if below_group:
                    # Minimum target price wins
                    min_alert = min(below_group, key=lambda x: x["target_price"])
                    final_alerts_to_send.append(min_alert)
                    
                if above_group:
                    # Maximum target price wins
                    max_alert = max(above_group, key=lambda x: x["target_price"])
                    final_alerts_to_send.append(max_alert)
            
            # 7. Action: Send messages and update triggered_state
            # Send alert only if triggered_state is 0
            for alert in final_alerts_to_send:
                alert_id = alert["id"]
                ticker = alert["ticker"]
                name = alert["name"]
                price = alert["current_price"]
                cond = alert["condition"]
                target = alert["target_price"]
                
                if alert["triggered_state"] == 0:
                    # Transition 0 -> 1: Send Telegram!
                    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    msg = f"🔔 *[주식 목표가 도달 알림]*\n\n*종목명:* {name}\n*티커:* `{ticker}`\n*현재가:* {price:,.2f}원\n*조건:* {cond} {target:,.2f}원\n*일시:* {timestamp}"
                    print(f"[{timestamp}] ALERT TRIGGERED: {name} ({ticker}) price {price} meets {cond} {target}")
                    
                    if token and chat_id:
                        success, resp = send_telegram(token, chat_id, msg)
                        if success:
                            database.update_alert_trigger_state(alert_id, 1, today_str)
                            print(f"[{ticker}] Telegram alert sent successfully.")
                        else:
                            print(f"[{ticker}] Failed to send Telegram: {resp}")
                    else:
                        database.update_alert_trigger_state(alert_id, 1, today_str)
                        print(f"[{ticker}] (Mock Mode) Alert marked as triggered in UI.")
            
            # 8. Reset state (1 -> 0) for non-triggered alerts
            # If an alert is NOT triggered, but its current triggered_state is 1,
            # it means the stock price has escaped the trigger boundary. We reset it to 0.
            for alert in non_triggered_alerts:
                if alert["triggered_state"] == 1:
                    alert_id = alert["id"]
                    ticker = alert["ticker"]
                    print(f"[{ticker}] Price escaped boundary. Resetting triggered_state from 1 to 0.")
                    database.update_alert_trigger_state(alert_id, 0)
                
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

class TelegramTokenRequest(BaseModel):
    telegram_token: str

@app.post("/api/get-chat-id")
def api_get_chat_id(data: TelegramTokenRequest):
    token = data.telegram_token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="봇 토큰이 입력되지 않았습니다.")
    
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    try:
        r = requests.get(url, timeout=5)
        if r.status_code != 200:
            raise HTTPException(status_code=400, detail=f"텔레그램 API 호출 실패 (상태 코드 {r.status_code}): {r.text}")
        
        res = r.json()
        if not res.get("ok"):
            raise HTTPException(status_code=400, detail=f"텔레그램 API 오류: {res.get('description', '알 수 없음')}")
        
        updates = res.get("result", [])
        if not updates:
            raise HTTPException(
                status_code=404, 
                detail="수신된 최근 메시지가 없습니다. 텔레그램 앱에서 봇에게 임의의 메시지(예: 봇 시작 또는 아무 글자)를 먼저 전송하신 후 다시 시도해 주세요."
            )
        
        # 최신 메시지에서 chat_id 추출
        latest_update = updates[-1]
        chat_id = None
        user_name = None
        
        # message, edited_message, callback_query, my_chat_member 등 파싱
        if "message" in latest_update:
            chat = latest_update["message"]["chat"]
            chat_id = chat.get("id")
            first_name = chat.get("first_name", "")
            last_name = chat.get("last_name", "")
            username = chat.get("username", "")
            user_name = first_name + (" " + last_name if last_name else "") or username or "Unknown"
        elif "edited_message" in latest_update:
            chat = latest_update["edited_message"]["chat"]
            chat_id = chat.get("id")
            first_name = chat.get("first_name", "")
            last_name = chat.get("last_name", "")
            username = chat.get("username", "")
            user_name = first_name + (" " + last_name if last_name else "") or username or "Unknown"
        elif "callback_query" in latest_update:
            chat = latest_update["callback_query"]["message"]["chat"]
            chat_id = chat.get("id")
            first_name = chat.get("first_name", "")
            last_name = chat.get("last_name", "")
            username = chat.get("username", "")
            user_name = first_name + (" " + last_name if last_name else "") or username or "Unknown"
        elif "my_chat_member" in latest_update:
            chat = latest_update["my_chat_member"]["chat"]
            chat_id = chat.get("id")
            first_name = chat.get("first_name", "")
            last_name = chat.get("last_name", "")
            username = chat.get("username", "")
            user_name = first_name + (" " + last_name if last_name else "") or username or "Unknown"
            
        if chat_id is None:
            raise HTTPException(status_code=404, detail="업데이트 데이터에서 Chat ID를 파싱할 수 없습니다.")
            
        return {
            "status": "success",
            "chat_id": str(chat_id),
            "user_name": user_name,
            "message": f"Chat ID 감지 성공: {user_name} ({chat_id})"
        }
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"네트워크 오류: {str(e)}")


@app.get("/api/search")
def api_search_stocks(q: str = ""):
    return stock_api.search_stocks(q)

@app.get("/api/alerts")
def api_list_alerts():
    return database.list_alerts()

@app.post("/api/alerts")
def api_create_alert(data: AlertCreate):
    if not data.ticker.strip() or not data.name.strip():
        raise HTTPException(status_code=400, detail="종목 코드와 종목명은 필수 입력 항목입니다. 종목을 올바르게 검색하여 선택해 주세요.")
        
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
    if not data.ticker.strip() or not data.name.strip():
        raise HTTPException(status_code=400, detail="종목 코드와 종목명은 필수 입력 항목입니다. 종목을 올바르게 검색하여 선택해 주세요.")
        
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

class BulkDeleteRequest(BaseModel):
    ids: list[int]

@app.post("/api/alerts/bulk-delete")
def api_delete_alerts_bulk(data: BulkDeleteRequest):
    try:
        database.delete_alerts_bulk(data.ids)
        return {"status": "success", "message": f"Successfully deleted {len(data.ids)} alerts."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to bulk delete alerts: {str(e)}")

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
        
        # Cache to store fetched prices
        price_cache = {}
        unique_tickers = list(set(a["ticker"] for a in active_alerts))
        for ticker in unique_tickers:
            price = stock_api.fetch_stock_price(ticker)
            price_cache[ticker] = price
            await asyncio.sleep(0.3)
            
        triggered_alerts = []
        non_triggered_alerts = []
        
        for alert in active_alerts:
            ticker = alert["ticker"]
            price = price_cache.get(ticker)
            if price is None:
                continue
                
            is_triggered = False
            cond = alert["condition"]
            target = alert["target_price"]
            
            if cond == "<=" and price <= target:
                is_triggered = True
            elif cond == ">=" and price >= target:
                is_triggered = True
            elif cond == "<" and price < target:
                is_triggered = True
            elif cond == ">" and price > target:
                is_triggered = True
                
            alert["current_price"] = price
            if is_triggered:
                triggered_alerts.append(alert)
            else:
                non_triggered_alerts.append(alert)
                
        # Priority Filter
        final_alerts_to_send = []
        ticker_groups = {}
        for alert in triggered_alerts:
            ticker_groups.setdefault(alert["ticker"], []).append(alert)
            
        for ticker, group in ticker_groups.items():
            below_group = [a for a in group if "<" in a["condition"]]
            above_group = [a for a in group if ">" in a["condition"]]
            if below_group:
                min_alert = min(below_group, key=lambda x: x["target_price"])
                final_alerts_to_send.append(min_alert)
            if above_group:
                max_alert = max(above_group, key=lambda x: x["target_price"])
                final_alerts_to_send.append(max_alert)
                
        # Action
        for alert in final_alerts_to_send:
            alert_id = alert["id"]
            if alert["triggered_state"] == 0:
                msg = f"🔔 *[수동 주가 진단 통과]*\n\n*종목명:* {alert['name']}\n*티커:* `{alert['ticker']}`\n*현재가:* {alert['current_price']:,.2f}원\n*조건:* {alert['condition']} {alert['target_price']:,.2f}원"
                if token and chat_id:
                    send_telegram(token, chat_id, msg)
                    database.update_alert_trigger_state(alert_id, 1, today_str)
                else:
                    database.update_alert_trigger_state(alert_id, 1, today_str)
                    
        # Reset State for escapes
        for alert in non_triggered_alerts:
            if alert["triggered_state"] == 1:
                database.update_alert_trigger_state(alert["id"], 0)
            
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
