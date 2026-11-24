import subprocess
import shutil
import json
import re
import time
import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger('scanner_magalu')

CURL_BIN = 'curl.exe' if shutil.which('curl.exe') else 'curl'
ANDROID_UA = 'Dalvik/2.1.0 (Linux; U; Android 12; Pixel 6)'

MAGALU_CATEGORIES = [
    ('celulares-e-smartphones', 'te', 'Smartphones & Celulares'),
    ('eletrodomesticos', 'ed', 'Eletrodomésticos'),
    ('tv-e-video', 'et', 'TV e Vídeo'),
    ('informatica', 'in', 'Informática & PCs'),
    ('moveis', 'mo', 'Móveis & Decoração'),
    ('eletroportateis', 'ep', 'Eletroportáteis'),
    ('ar-e-ventilacao', 'ar', 'Ar e Ventilação'),
    ('beleza-e-perfumaria', 'pf', 'Dermo & Beleza')
]

def classify_magalu_bug(name: str, brand: str, list_price: float, sell_price: float, discount_pct: float, savings: float):
    is_bug = False
    reasons = []
    score = 0
    
    if discount_pct >= 80:
        is_bug = True
        score += 85
        reasons.append(f"🔥 Desconto Brutal Magalu ({discount_pct:.1f}% OFF)")
    elif discount_pct >= 65:
        is_bug = True
        score += 65
        reasons.append(f"⚡ Super Desconto ({discount_pct:.1f}% OFF)")
    elif discount_pct >= 50:
        score += 35
        reasons.append(f"🏷️ Oferta Destaque ({discount_pct:.1f}% OFF)")

    # Erro de preço ou centavos em itens caros
    if list_price >= 200.00 and sell_price <= 49.00 and sell_price > 0:
        is_bug = True
        score += 85
        reasons.append(f"💸 Erro de Preço/Centavos (R$ {sell_price:.2f} de R$ {list_price:.2f})")
        
    if savings >= 800.00 and discount_pct >= 40:
        is_bug = True
        score += 60
        reasons.append(f"💰 Economia Gigante (Economize R$ {savings:.2f})")
    elif savings >= 400.00 and discount_pct >= 35:
        score += 30
        reasons.append(f"💰 Grande Economia (R$ {savings:.2f})")
        
    final_score = max(0, min(100, score))
    return is_bug, final_score, reasons

def fetch_magalu_category(cat_name: str, cat_code: str, dept_name: str) -> list:
    url = f"https://m.magazineluiza.com.br/{cat_name}/l/{cat_code}/"
    try:
        res = subprocess.run(
            [CURL_BIN, '-s', '-A', ANDROID_UA, url],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors='ignore',
            timeout=15
        )
        if not res.stdout:
            return []
            
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', res.stdout)
        if not m:
            return []
            
        data = json.loads(m.group(1))
        items = data.get('props', {}).get('pageProps', {}).get('data', {}).get('search', {}).get('items', [])
        
        parsed_list = []
        for p in items:
            p_id = str(p.get('id') or '')
            if not p_id:
                continue
                
            name = (p.get('title') or '').strip()
            if not name:
                continue
                
            brand_raw = p.get('brand')
            brand = brand_raw.get('label') if isinstance(brand_raw, dict) else str(brand_raw or 'Magazine Luiza')
            
            raw_path = p.get('path') or ''
            link = f"https://www.magazineluiza.com.br{raw_path}" if raw_path.startswith('/') else f"https://www.magazineluiza.com.br/{raw_path}"
            image_raw = p.get('image') or ''
            image = image_raw.replace('{w}x{h}', '400x400')
            
            offers = p.get('offers', [])
            off = offers[0] if offers and isinstance(offers[0], dict) else {}
            
            list_price = float(off.get('listPrice') or 0.0)
            best_amount = off.get('bestPrice', {}).get('totalAmount') if isinstance(off.get('bestPrice'), dict) else None
            sell_price = float(best_amount or off.get('price') or 0.0)
            
            if sell_price <= 0:
                continue
                
            if list_price < sell_price:
                list_price = sell_price
                
            savings = round(list_price - sell_price, 2) if list_price > sell_price else 0.0
            discount_pct = round((savings / list_price) * 100, 1) if list_price > 0 else 0.0
            available = bool(p.get('available', True))
            stock_qty = 999 if available else 0
            
            is_bug, bug_score, bug_reasons = classify_magalu_bug(
                name, brand, list_price, sell_price, discount_pct, savings
            )
            
            clean_search = re.sub(r'[^\w\s]', ' ', name).strip()
            first_words = '+'.join(clean_search.split()[:4])
            
            comparison_urls = {
                'google_shopping': f"https://www.google.com.br/search?q={first_words}&tbm=shop",
                'buscape': f"https://www.buscape.com.br/search?q={first_words}"
            }
            
            prod_dict = {
                'id': f"mag_{p_id}",
                'name': name,
                'brand': brand,
                'category': dept_name,
                'department': dept_name,
                'all_categories': [dept_name, cat_name],
                'store': 'Magazine Luiza',
                'ean': '',
                'link': link,
                'image': image,
                'list_price': list_price,
                'sell_price': sell_price,
                'discount_pct': discount_pct,
                'savings': savings,
                'available': available,
                'stock_quantity': stock_qty,
                'is_bug': is_bug,
                'bug_score': bug_score,
                'bug_reasons': bug_reasons,
                'comparison_urls': comparison_urls,
                'market_verified': False,
                'market_store': '',
                'market_price': 0.0,
                'real_savings': 0.0,
                'real_discount_pct': 0.0
            }
            parsed_list.append(prod_dict)
            
        logger.info(f"Magalu [{cat_name}]: {len(parsed_list)} produtos minerados com sucesso.")
        return parsed_list
    except Exception as e:
        logger.error(f"Erro ao minerar Magalu {cat_name}: {e}")
        return []

def scan_magalu_promos() -> list:
    """Varre todas as categorias da Magazine Luiza em paralelo."""
    logger.info("Iniciando varredura paralela da Magazine Luiza...")
    t0 = time.time()
    all_magalu = []
    
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(fetch_magalu_category, name, code, dept)
            for name, code, dept in MAGALU_CATEGORIES
        ]
        for f in futures:
            try:
                res = f.result()
                if res:
                    all_magalu.extend(res)
            except Exception as e:
                logger.warning(f"Erro em thread Magalu: {e}")
                
    elapsed = round(time.time() - t0, 2)
    logger.info(f"Varredura Magalu finalizada em {elapsed}s: {len(all_magalu)} produtos capturados.")
    return all_magalu
