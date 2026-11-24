import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'promos.db')

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            brand TEXT,
            category TEXT,
            department TEXT,
            all_categories TEXT,
            link TEXT,
            image TEXT,
            list_price REAL,
            sell_price REAL,
            discount_pct REAL,
            savings REAL,
            available INTEGER,
            stock_quantity INTEGER,
            is_bug INTEGER,
            bug_score INTEGER,
            bug_reasons TEXT,
            first_seen TIMESTAMP,
            last_seen TIMESTAMP,
            times_seen INTEGER DEFAULT 1
        )
    ''')
    
    # Check if department column exists (migration)
    c.execute("PRAGMA table_info(products)")
    columns = [row[1] for row in c.fetchall()]
    if 'department' not in columns:
        c.execute("ALTER TABLE products ADD COLUMN department TEXT")
    if 'ean' not in columns:
        c.execute("ALTER TABLE products ADD COLUMN ean TEXT")
    if 'market_verified' not in columns:
        c.execute("ALTER TABLE products ADD COLUMN market_verified INTEGER DEFAULT 0")
    if 'market_price' not in columns:
        c.execute("ALTER TABLE products ADD COLUMN market_price REAL DEFAULT 0")
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS scan_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP,
            total_scanned INTEGER,
            total_promos INTEGER,
            total_bugs INTEGER,
            duration_seconds REAL,
            status TEXT
        )
    ''')
    
    # Indexes
    c.execute('CREATE INDEX IF NOT EXISTS idx_discount ON products(discount_pct)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_is_bug ON products(is_bug)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_available ON products(available)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_category ON products(category)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_department ON products(department)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_sell_price ON products(sell_price)')
    
    conn.commit()
    conn.close()

def bulk_upsert_products(product_list: list):
    """Insere ou atualiza múltiplos produtos em uma única transação ultra-rápida."""
    if not product_list:
        return
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    
    for prod in product_list:
        dept = prod.get('department') or 'Geral'
        c.execute('''
            INSERT INTO products (
                id, name, brand, category, department, all_categories,
                link, image, list_price, sell_price,
                discount_pct, savings, available, stock_quantity,
                is_bug, bug_score, bug_reasons,
                first_seen, last_seen, times_seen
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                brand = excluded.brand,
                category = excluded.category,
                department = excluded.department,
                all_categories = excluded.all_categories,
                link = excluded.link,
                image = excluded.image,
                list_price = excluded.list_price,
                sell_price = excluded.sell_price,
                discount_pct = excluded.discount_pct,
                savings = excluded.savings,
                available = excluded.available,
                stock_quantity = excluded.stock_quantity,
                is_bug = excluded.is_bug,
                bug_score = excluded.bug_score,
                bug_reasons = excluded.bug_reasons,
                last_seen = excluded.last_seen,
                times_seen = products.times_seen + 1
        ''', (
            prod['id'], prod['name'], prod['brand'], prod['category'], dept, json.dumps(prod.get('all_categories', [])),
            prod['link'], prod['image'], prod['list_price'], prod['sell_price'],
            prod['discount_pct'], prod['savings'], 1 if prod['available'] else 0, prod['stock_quantity'],
            1 if prod['is_bug'] else 0, prod['bug_score'], json.dumps(prod.get('bug_reasons', [])),
            now, now
        ))
    
    conn.commit()
    conn.close()

def log_scan(total_scanned, total_promos, total_bugs, duration, status="SUCCESS"):
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute('''
        INSERT INTO scan_history (timestamp, total_scanned, total_promos, total_bugs, duration_seconds, status)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (now, total_scanned, total_promos, total_bugs, duration, status))
    conn.commit()
    conn.close()

def get_stats():
    conn = get_connection()
    c = conn.cursor()
    
    c.execute('SELECT COUNT(*) FROM products')
    total = c.fetchone()[0]
    
    c.execute('SELECT COUNT(*) FROM products WHERE discount_pct >= 70')
    over_70 = c.fetchone()[0]
    
    c.execute('SELECT COUNT(*) FROM products WHERE discount_pct >= 80')
    over_80 = c.fetchone()[0]
    
    c.execute('SELECT COUNT(*) FROM products WHERE is_bug = 1')
    bugs = c.fetchone()[0]
    
    c.execute('SELECT COUNT(*) FROM products WHERE available = 1 AND discount_pct >= 70')
    in_stock_70 = c.fetchone()[0]
    
    c.execute('SELECT MAX(savings) FROM products WHERE available = 1')
    max_savings = c.fetchone()[0] or 0.0
    
    c.execute('SELECT timestamp, duration_seconds, status FROM scan_history ORDER BY id DESC LIMIT 1')
    last_scan = c.fetchone()
    
    conn.close()
    return {
        'total_products': total,
        'over_70': over_70,
        'over_80': over_80,
        'bugs': bugs,
        'in_stock_70': in_stock_70,
        'max_savings': round(max_savings, 2),
        'last_scan': dict(last_scan) if last_scan else None
    }
