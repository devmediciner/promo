import os
import json
import csv
import io
import time
import threading
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response

from database import get_connection, get_stats, init_db
from scanner import run_full_scan

app = FastAPI(title="Pague Menos PromoBug Radar", version="2.2.0")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_HTML_PATH = os.path.join(BASE_DIR, "index.html")
if not os.path.exists(INDEX_HTML_PATH):
    INDEX_HTML_PATH = os.path.join(BASE_DIR, "templates", "index.html")

AUTO_SCAN_INTERVAL = int(os.environ.get("AUTO_SCAN_INTERVAL", 600))

scan_state = {
    "is_scanning": False,
    "last_result": None,
    "last_error": None,
    "next_scheduled_scan": None
}

def scan_worker():
    global scan_state
    if scan_state["is_scanning"]:
        return
    scan_state["is_scanning"] = True
    scan_state["last_error"] = None
    try:
        res = run_full_scan()
        scan_state["last_result"] = res
    except Exception as e:
        scan_state["last_error"] = str(e)
    finally:
        scan_state["is_scanning"] = False
        scan_state["next_scheduled_scan"] = time.time() + AUTO_SCAN_INTERVAL

def background_scheduler_loop():
    time.sleep(3)
    scan_worker()
    while True:
        time.sleep(15)
        now = time.time()
        next_scan = scan_state.get("next_scheduled_scan")
        if next_scan and now >= next_scan and not scan_state["is_scanning"]:
            scan_worker()

@app.on_event("startup")
def startup_event():
    init_db()
    threading.Thread(target=background_scheduler_loop, daemon=True).start()

@app.get("/", response_class=HTMLResponse)
def index():
    with open(INDEX_HTML_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    return HTMLResponse(content=content)

@app.get("/data/promos.json")
def get_promos_json():
    json_path = os.path.join(BASE_DIR, "data", "promos.json")
    if not os.path.exists(json_path):
        json_path = os.path.join(BASE_DIR, "promos.json")
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            return JSONResponse(content=json.load(f))
    return JSONResponse(status_code=404, content={"error": "promos.json não encontrado"})

@app.get("/api/stats")
def api_stats():
    stats = get_stats()
    stats["is_scanning"] = scan_state["is_scanning"]
    stats["last_scan_result"] = scan_state["last_result"]
    stats["next_scheduled_scan"] = scan_state["next_scheduled_scan"]
    stats["auto_interval_minutes"] = AUTO_SCAN_INTERVAL // 60
    return stats

@app.post("/api/scan")
def trigger_scan():
    global scan_state
    if scan_state["is_scanning"]:
        return JSONResponse(status_code=409, content={"status": "already_running", "message": "Varredura já está em andamento."})
    
    threading.Thread(target=scan_worker, daemon=True).start()
    return {"status": "started", "message": "Varredura geral de promoções iniciada em segundo plano!"}

@app.get("/api/promos")
def get_promos(
    min_discount: float = Query(70.0, ge=0, le=100),
    max_price: Optional[float] = Query(None, ge=0),
    min_price: Optional[float] = Query(None, ge=0),
    department: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    brand: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    in_stock_only: bool = Query(False),
    promobug_only: bool = Query(False),
    exclude_medicines: bool = Query(False),
    sort: str = Query("discount_desc"),
    page: int = Query(1, ge=1),
    limit: int = Query(30, ge=1, le=100)
):
    conn = get_connection()
    c = conn.cursor()
    
    query = "SELECT * FROM products WHERE discount_pct >= ?"
    params = [min_discount]
    
    if max_price is not None:
        query += " AND sell_price <= ?"
        params.append(max_price)
        
    if min_price is not None:
        query += " AND sell_price >= ?"
        params.append(min_price)
        
    if in_stock_only:
        query += " AND available = 1"
        
    if promobug_only:
        query += " AND is_bug = 1"
        
    if exclude_medicines:
        query += """ AND (
            department NOT LIKE '%Medicamento%'
            AND category NOT LIKE '%Medicamento%'
            AND all_categories NOT LIKE '%Medicamentos e Saúde%'
            AND name NOT LIKE '%comprimido%'
            AND name NOT LIKE '%genérico%'
            AND name NOT LIKE '%generico%'
            AND name NOT LIKE '%cápsula dura%'
            AND name NOT LIKE '%capsula dura%'
            AND name NOT LIKE '%gotas %'
            AND name NOT LIKE '%xarope%'
            AND name NOT LIKE '%solução oral%'
            AND name NOT LIKE '%suspensão oral%'
            AND name NOT LIKE '%injetável%'
        )"""
        
    if department and department.lower() != 'todos':
        query += " AND (department LIKE ? OR all_categories LIKE ?)"
        params.extend([f"%{department}%", f"%{department}%"])

    if category:
        query += " AND (category LIKE ? OR all_categories LIKE ?)"
        params.extend([f"%{category}%", f"%{category}%"])
        
    if brand:
        query += " AND brand LIKE ?"
        params.append(f"%{brand}%")
        
    if search:
        query += " AND (name LIKE ? OR brand LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
        
    count_query = f"SELECT COUNT(*) FROM ({query})"
    c.execute(count_query, params)
    total_matching = c.fetchone()[0]
    
    sort_map = {
        "discount_desc": "discount_pct DESC, savings DESC",
        "savings_desc": "savings DESC, discount_pct DESC",
        "price_asc": "sell_price ASC",
        "price_desc": "sell_price DESC",
        "bug_score_desc": "bug_score DESC, discount_pct DESC",
        "recent": "first_seen DESC",
    }
    order_clause = sort_map.get(sort, "discount_pct DESC")
    query += f" ORDER BY {order_clause} LIMIT ? OFFSET ?"
    
    offset = (page - 1) * limit
    params.extend([limit, offset])
    
    c.execute(query, params)
    rows = c.fetchall()
    
    items = []
    for r in rows:
        d = dict(r)
        d["all_categories"] = json.loads(d["all_categories"]) if d.get("all_categories") else []
        d["bug_reasons"] = json.loads(d["bug_reasons"]) if d.get("bug_reasons") else []
        items.append(d)
        
    conn.close()
    
    total_pages = (total_matching + limit - 1) // limit if total_matching > 0 else 1
    
    return {
        "total": total_matching,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "products": items
    }

@app.get("/api/departments")
def get_departments():
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        SELECT department, COUNT(*) as total_items,
               SUM(CASE WHEN discount_pct >= 70 THEN 1 ELSE 0 END) as promo_70,
               SUM(CASE WHEN is_bug = 1 THEN 1 ELSE 0 END) as bugs
        FROM products
        WHERE department IS NOT NULL AND department != ''
        GROUP BY department
        ORDER BY promo_70 DESC, total_items DESC
    ''')
    depts = [dict(r) for r in c.fetchall()]
    conn.close()
    return depts

@app.get("/api/categories")
def get_categories():
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        SELECT category, department, COUNT(*) as total_items,
               SUM(CASE WHEN discount_pct >= 70 THEN 1 ELSE 0 END) as promo_70,
               SUM(CASE WHEN is_bug = 1 THEN 1 ELSE 0 END) as bugs
        FROM products
        WHERE category IS NOT NULL AND category != ''
        GROUP BY category
        ORDER BY promo_70 DESC, total_items DESC
    ''')
    cats = [dict(r) for r in c.fetchall()]
    conn.close()
    return cats

@app.get("/api/export/csv")
def export_csv(
    min_discount: float = 70.0,
    department: Optional[str] = None,
    promobug_only: bool = False,
    in_stock_only: bool = False,
    exclude_medicines: bool = False
):
    conn = get_connection()
    c = conn.cursor()
    query = "SELECT name, brand, department, category, list_price, sell_price, discount_pct, savings, available, stock_quantity, is_bug, bug_score, link FROM products WHERE discount_pct >= ?"
    params = [min_discount]
    if exclude_medicines:
        query += """ AND (
            department NOT LIKE '%Medicamento%'
            AND category NOT LIKE '%Medicamento%'
            AND all_categories NOT LIKE '%Medicamentos e Saúde%'
            AND name NOT LIKE '%comprimido%'
            AND name NOT LIKE '%genérico%'
            AND name NOT LIKE '%generico%'
        )"""
    if department and department.lower() != 'todos':
        query += " AND department LIKE ?"
        params.append(f"%{department}%")
    if promobug_only:
        query += " AND is_bug = 1"
    if in_stock_only:
        query += " AND available = 1"
    query += " ORDER BY discount_pct DESC"
    
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow([
        "Produto", "Marca", "Departamento", "Categoria", "Preço De (R$)", "Preço Por (R$)",
        "Desconto (%)", "Economia (R$)", "Disponível", "Estoque", "PromoBug", "Score Bug", "Link Direto"
    ])
    for r in rows:
        writer.writerow([
            r["name"], r["brand"], r["department"], r["category"],
            f"{r['list_price']:.2f}", f"{r['sell_price']:.2f}",
            f"{r['discount_pct']:.1f}%", f"{r['savings']:.2f}",
            "SIM" if r["available"] else "NÃO", r["stock_quantity"],
            "SIM" if r["is_bug"] else "NÃO", r["bug_score"], r["link"]
        ])
        
    csv_content = "\ufeff" + output.getvalue()
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=paguemenos_promos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"}
    )
