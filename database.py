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
    
    # 2. Check if alerts table exists and check if ticker is UNIQUE
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='alerts'")
    table_info = cursor.fetchone()
    
    needs_migration = False
    if table_info:
        sql_stmt = table_info[0]
        if "UNIQUE" in sql_stmt.upper() or "UNIQUE" in sql_stmt:
            needs_migration = True
            
    if needs_migration:
        print("Migrating database: Removing UNIQUE constraint from ticker column...")
        try:
            # Begin transaction for safety
            cursor.execute("BEGIN TRANSACTION")
            
            # Backup table
            cursor.execute("ALTER TABLE alerts RENAME TO alerts_old")
            
            # Create new table without UNIQUE constraint
            cursor.execute("""
            CREATE TABLE alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT,
                name TEXT,
                condition TEXT,
                target_price REAL,
                enabled INTEGER DEFAULT 1,
                last_alert_date TEXT,
                triggered_state INTEGER DEFAULT 0
            )
            """)
            
            # Restore data
            cursor.execute("""
            INSERT INTO alerts (id, ticker, name, condition, target_price, enabled, last_alert_date, triggered_state)
            SELECT id, ticker, name, condition, target_price, enabled, last_alert_date, 0 FROM alerts_old
            """)
            
            # Drop backup table
            cursor.execute("DROP TABLE alerts_old")
            conn.commit()
            print("Database migration completed successfully.")
        except Exception as e:
            conn.rollback()
            print(f"Error during migration: {e}")
    else:
        # Create table if not exists (fresh start or already migrated)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT,
            name TEXT,
            condition TEXT, -- '<=', '>=', '<', '>'
            target_price REAL,
            enabled INTEGER DEFAULT 1, -- 0 = Disabled, 1 = Enabled
            last_alert_date TEXT, -- Format: YYYY-MM-DD
            triggered_state INTEGER DEFAULT 0
        )
        """)
        
        # Check if table exists but is missing 'triggered_state' column (for existing tables without UNIQUE)
        if table_info:
            cursor.execute("PRAGMA table_info(alerts)")
            columns = [col[1] for col in cursor.fetchall()]
            if "triggered_state" not in columns:
                print("Migrating database: Adding triggered_state column...")
                try:
                    cursor.execute("ALTER TABLE alerts ADD COLUMN triggered_state INTEGER DEFAULT 0")
                    conn.commit()
                    print("Added triggered_state column successfully.")
                except Exception as e:
                    print(f"Error adding triggered_state column: {e}")
        
        # Insert some sample alerts for UI testing if table is empty
        cursor.execute("SELECT COUNT(*) FROM alerts")
        if cursor.fetchone()[0] == 0:
            sample_alerts = [
                ("005930.KS", "삼성전자", "<=", 70000.0, 1, "", 0),
                ("AAPL", "Apple Inc.", ">=", 180.0, 1, "", 0),
                ("NVDA", "NVIDIA Corp.", ">=", 120.0, 0, "", 0)
            ]
            cursor.executemany("""
            INSERT INTO alerts (ticker, name, condition, target_price, enabled, last_alert_date, triggered_state)
            VALUES (?, ?, ?, ?, ?, ?, ?)
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
    cursor.execute("SELECT id, ticker, name, condition, target_price, enabled, last_alert_date, triggered_state FROM alerts")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def create_alert(ticker, name, condition, target_price, enabled=1):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Check if the exact same rule (ticker, condition, target_price) already exists
        cursor.execute("""
        SELECT COUNT(*) FROM alerts 
        WHERE ticker = ? AND condition = ? AND target_price = ?
        """, (ticker.strip().upper(), condition.strip(), float(target_price)))
        
        if cursor.fetchone()[0] > 0:
            return False, f"이미 동일한 조건의 알림이 등록되어 있습니다. ({ticker} - {condition} {target_price})"
            
        cursor.execute("""
        INSERT INTO alerts (ticker, name, condition, target_price, enabled, last_alert_date, triggered_state)
        VALUES (?, ?, ?, ?, ?, ?, 0, 0)
        """, (ticker.strip().upper(), name.strip(), condition.strip(), float(target_price), int(enabled), ""))
        conn.commit()
        success = True
        error_msg = ""
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
        # Check if another alert has the exact same rule (ticker, condition, target_price)
        cursor.execute("""
        SELECT COUNT(*) FROM alerts 
        WHERE ticker = ? AND condition = ? AND target_price = ? AND id != ?
        """, (ticker.strip().upper(), condition.strip(), float(target_price), int(alert_id)))
        
        if cursor.fetchone()[0] > 0:
            return False, f"이미 동일한 조건의 다른 알림이 등록되어 있습니다. ({ticker} - {condition} {target_price})"
            
        cursor.execute("""
        UPDATE alerts 
        SET ticker = ?, name = ?, condition = ?, target_price = ?, enabled = ?, triggered_state = 0
        WHERE id = ?
        """, (ticker.strip().upper(), name.strip(), condition.strip(), float(target_price), int(enabled), int(alert_id)))
        conn.commit()
        success = True
        error_msg = ""
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

def delete_alerts_bulk(alert_ids):
    if not alert_ids:
        return
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholders = ','.join('?' for _ in alert_ids)
    cursor.execute(f"DELETE FROM alerts WHERE id IN ({placeholders})", [int(x) for x in alert_ids])
    conn.commit()
    conn.close()

def update_last_alert_date(alert_id, date_str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE alerts SET last_alert_date = ? WHERE id = ?", (date_str, int(alert_id)))
    conn.commit()
    conn.close()

def update_alert_trigger_state(alert_id, state, date_str=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    if date_str:
        cursor.execute("""
        UPDATE alerts 
        SET triggered_state = ?, last_alert_date = ? 
        WHERE id = ?
        """, (int(state), date_str, int(alert_id)))
    else:
        cursor.execute("""
        UPDATE alerts 
        SET triggered_state = ? 
        WHERE id = ?
        """, (int(state), int(alert_id)))
    conn.commit()
    conn.close()
