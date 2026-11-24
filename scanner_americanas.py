import subprocess
import shutil
import json
import re
import time
import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger('scanner_americanas')

CURL_BIN = 'curl.exe' if shutil.which('curl.exe') else 'curl'

AMERICANAS_CATEGORIES = [
    ('celulares-e-smartphones', 'Smartphones & Celulares'),
    ('eletrodomesticos', 'Eletrodomésticos'),
    ('tv-e-home-theater', 'TV e Vídeo'),
    ('informatica', 'Informática & PCs'),
    ('moveis', 'Móveis & Decoração'),
    ('beleza-e-perfumaria', 'Dermo & Beleza'),
    ('eletroportateis', 'Eletroportáteis')
]

def classify_americanas_bug(name: str, brand: str, list_price: float, sell_price: float, discount_pct: float, savings: float):
    is_bug = False
    reasons = []
    score = 0
    
    if discount_pct >= 80:
        is_bug = True
        score += 85
        reasons.append(f"🔥 Desconto Brutal Americanas ({discount_pct:.1f}% OFF)")
    elif discount_pct >= 65:
        is_bug = True
        score += 65
        reasons.append(f"⚡ Super Desconto ({discount_pct:.1f}% OFF)")
    elif discount_pct >= 50:
        score += 35
        reasons.append(f"🏷️ Oferta Destaque ({discount_pct:.1f}% OFF)")

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

def fetch_americanas_category(slug: str, dept_name: str) -> list:
    url = f"https://www.americanas.com.br/categoria/{slug}"
    try:
        res = subprocess.run(
            [CURL_BIN, '-s', '-L', url],
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
        edges = data.get('props', {}).get('pageProps', {}).get('data', {}).get('search', {}).get('products', {}).get('edges', [])
        
        parsed_list = []
        for edge in edges:
            node = edge.get('node', {})
            p_id = str(node.get('id') or node.get('sku') or '')
            if not p_id:
                continue
                
            name = (node.get('name') or '').strip()
            if not name:
                continue
                
            brand_raw = node.get('brand')
            brand = brand_raw.get('name') if isinstance(brand_raw, dict) else str(brand_raw or 'Americanas')
            
            slug_prod = node.get('slug') or ''
            link = f"https://www.americanas.com.br/{slug_prod}/p" if slug_prod else f"https://www.americanas.com.br/{node.get('link', '')}"
            
            images = node.get('image', [])
            image = images[0].get('url', '') if images and isinstance(images, list) else ''
            
            ean = str(node.get('gtin') or '')
            
            offers_obj = node.get('offers', {})
            offers_list = offers_obj.get('offers', [])
            off = offers_list[0] if offers_list and isinstance(offers_list[0], dict) else {}
            
            list_price = float(off.get('listPrice') or offers_obj.get('lowPrice') or 0.0)
            sell_price = float(off.get('price') or offers_obj.get('lowPrice') or 0.0)
            
            if sell_price <= 0:
                continue
                
            if list_price < sell_price:
                list_price = sell_price
                
            savings = round(list_price - sell_price, 2) if list_price > sell_price else 0.0
            discount_pct = round((savings / list_price) * 100, 1) if list_price > 0 else 0.0
            avail_str = str(off.get('availability') or '')
            available = 'InStock' in avail_str if avail_str else True
            stock_qty = int(off.get('quantity') or (999 if available else 0))
            
            is_bug, bug_score, bug_reasons = classify_americanas_bug(
                name, brand, list_price, sell_price, discount_pct, savings
            )
            
            clean_search = re.sub(r'[^\w\s]', ' ', name).strip()
            first_words = '+'.join(clean_search.split()[:4])
            query_val = ean if ean else first_words
            
            comparison_urls = {
                'google_shopping': f"https://www.google.com.br/search?q={query_val}&tbm=shop",
                'buscape': f"https://www.buscape.com.br/search?q={query_val}"
            }
            
            prod_dict = {
                'id': f"ame_{p_id}",
                'name': name,
                'brand': brand,
                'category': dept_name,
                'department': dept_name,
                'all_categories': [dept_name, slug],
                'store': 'Americanas',
                'ean': ean,
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
            
        logger.info(f"Americanas [{slug}]: {len(parsed_list)} produtos minerados com sucesso.")
        return parsed_list
    except Exception as e:
        logger.error(f"Erro ao minerar Americanas {slug}: {e}")
        return []

def scan_americanas_promos() -> list:
    """Varre todas as categorias da Americanas em paralelo."""
    logger.info("Iniciando varredura paralela da Americanas...")
    t0 = time.time()
    all_ame = []
    
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(fetch_americanas_category, slug, dept)
            for slug, dept in AMERICANAS_CATEGORIES
        ]
        for f in futures:
            try:
                res = f.result()
                if res:
                    all_ame.extend(res)
            except Exception as e:
                logger.warning(f"Erro em thread Americanas: {e}")
                
    elapsed = round(time.time() - t0, 2)
    logger.info(f"Varredura Americanas finalizada em {elapsed}s: {len(all_ame)} produtos capturados.")
    return all_ame
