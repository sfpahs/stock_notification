import sqlite3
import os
from config import DATABASE_PATH, DEFAULT_CHECK_INTERVAL, DEFAULT_TELEGRAM_TOKEN, DEFAULT_TELEGRAM_CHAT_ID

def get_db_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row  # Enables accessing columns by name
    return conn

def init_db():
    """Initializes the database and creates tables if they do not exist."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Create settings table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        telegram_token TEXT,
        telegram_chat_id TEXT,
        check_interval INTEGER DEFAULT 60
    )
    """)
    
    # Insert default settings if empty
    cursor.execute("SELECT COUNT(*) FROM settings")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
        INSERT INTO settings (id, telegram_token, telegram_chat_id, check_interval)
        VALUES (1, ?, ?, ?)
        """, (DEFAULT_TELEGRAM_TOKEN, DEFAULT_TELEGRAM_CHAT_ID, DEFAULT_CHECK_INTERVAL))
    
    # 2. Create alerts table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker TEXT UNIQUE,
        name TEXT,
        condition TEXT, -- '<=', '>=', '<', '>'
        target_price REAL,
        enabled INTEGER DEFAULT 1, -- 0 = Disabled, 1 = Enabled
        last_alert_date TEXT -- Format: YYYY-MM-DD
    )
    """)
    
    # Insert some sample alerts for UI testing if table is empty
    cursor.execute("SELECT COUNT(*) FROM alerts")
    if cursor.fetchone()[0] == 0:
        sample_alerts = [
            ("005930.KS", "삼성전자", "<=", 70000.0, 1, ""),
            ("AAPL", "Apple Inc.", ">=", 180.0, 1, ""),
            ("NVDA", "NVIDIA Corp.", ">=", 120.0, 0, "")
        ]
        cursor.executemany("""
        INSERT INTO alerts (ticker, name, condition, target_price, enabled, last_alert_date)
        VALUES (?, ?, ?, ?, ?, ?)
        """, sample_alerts)
        
    conn.commit()
    conn.close()

# --- Settings DB Operations ---

def get_settings():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT telegram_token, telegram_chat_id, check_interval FROM settings WHERE id = 1")
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return {
        "telegram_token": DEFAULT_TELEGRAM_TOKEN,
        "telegram_chat_id": DEFAULT_TELEGRAM_CHAT_ID,
        "check_interval": DEFAULT_CHECK_INTERVAL
    }

def update_settings(telegram_token, telegram_chat_id, check_interval):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE settings 
    SET telegram_token = ?, telegram_chat_id = ?, check_interval = ? 
    WHERE id = 1
    """, (telegram_token.strip(), telegram_chat_id.strip(), int(check_interval)))
    conn.commit()
    conn.close()

# --- Alerts DB Operations ---

def list_alerts():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, ticker, name, condition, target_price, enabled, last_alert_date FROM alerts")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def create_alert(ticker, name, condition, target_price, enabled=1):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
        INSERT INTO alerts (ticker, name, condition, target_price, enabled, last_alert_date)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (ticker.strip().upper(), name.strip(), condition.strip(), float(target_price), int(enabled), ""))
        conn.commit()
        success = True
        error_msg = ""
    except sqlite3.IntegrityError:
        success = False
        error_msg = f"Ticker '{ticker}' is already registered."
    except Exception as e:
        success = False
        error_msg = str(e)
    finally:
        conn.close()
    return success, error_msg

def update_alert(alert_id, ticker, name, condition, target_price, enabled):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
        UPDATE alerts 
        SET ticker = ?, name = ?, condition = ?, target_price = ?, enabled = ?
        WHERE id = ?
        """, (ticker.strip().upper(), name.strip(), condition.strip(), float(target_price), int(enabled), int(alert_id)))
        conn.commit()
        success = True
        error_msg = ""
    except sqlite3.IntegrityError:
        success = False
        error_msg = f"Ticker '{ticker}' is already registered by another alert."
    except Exception as e:
        success = False
        error_msg = str(e)
    finally:
        conn.close()
    return success, error_msg

def delete_alert(alert_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM alerts WHERE id = ?", (int(alert_id),))
    conn.commit()
    conn.close()

def update_last_alert_date(alert_id, date_str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE alerts SET last_alert_date = ? WHERE id = ?", (date_str, int(alert_id)))
    conn.commit()
    conn.close()
