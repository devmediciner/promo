import subprocess
import shutil
import json
import re
import time
import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger('scanner_drogasil')

CURL_BIN = 'curl.exe' if shutil.which('curl.exe') else 'curl'

DROGASIL_CATEGORIES = [
    ('dermocosmeticos.html', 'Dermo & Beleza'),
    ('beleza.html', 'Beleza & Higiene'),
    ('cuidados-diarios.html', 'Cuidados Diários'),
    ('mamae-e-bebe.html', 'Mamãe e Bebê'),
    ('saude.html', 'Saúde & Nutrição')
]

def classify_drogasil_bug(name: str, brand: str, list_price: float, sell_price: float, discount_pct: float, savings: float):
    is_bug = False
    reasons = []
    score = 0
    
    # Erro de preço bizarro (ex: Dermocosmético ou Perfume por centavos ou menos de R$ 5,00)
    if sell_price <= 5.00 and sell_price > 0:
        is_bug = True
        score += 90
        reasons.append(f"💸 Preço Anômalo/Centavos (Por R$ {sell_price:.2f})")
    elif discount_pct >= 80:
        is_bug = True
        score += 85
        reasons.append(f"🔥 Desconto Brutal Drogasil ({discount_pct:.1f}% OFF)")
    elif discount_pct >= 65:
        is_bug = True
        score += 65
        reasons.append(f"⚡ Super Desconto ({discount_pct:.1f}% OFF)")
    elif discount_pct >= 45:
        score += 35
        reasons.append(f"🏷️ Oferta Destaque ({discount_pct:.1f}% OFF)")
        
    if savings >= 100.00:
        is_bug = True
        score += 50
        reasons.append(f"💰 Economia de R$ {savings:.2f}")
        
    final_score = max(0, min(100, score))
    return is_bug, final_score, reasons

def fetch_drogasil_category(cat_file: str, dept_name: str) -> list:
    url = f"https://www.drogasil.com.br/{cat_file}"
    try:
        res = subprocess.run(
            [CURL_BIN, '-s', url],
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
        prods = data.get('props', {}).get('pageProps', {}).get('pageProps', {}).get('results', {}).get('products', [])
        
        parsed_list = []
        for p in prods:
            sku = str(p.get('sku') or p.get('objectID') or '')
            if not sku:
                continue
                
            name = (p.get('name') or '').strip()
            if not name:
                continue
                
            brand = (p.get('brand') or 'Drogasil').strip()
            raw_url = p.get('url') or ''
            link = f"https://www.drogasil.com.br{raw_url}" if raw_url.startswith('/') else f"https://www.drogasil.com.br/{raw_url}"
            
            img_dict = p.get('image') or {}
            image = img_dict.get('src') if isinstance(img_dict, dict) else str(img_dict or '')
            
            sell_price = float(p.get('priceService') or 0.0)
            if sell_price <= 0:
                continue
                
            # Verifica se há labels promocionais (ex: desconto percentual)
            labels = p.get('labels', [])
            discount_pct = 0.0
            list_price = sell_price
            
            for l in labels:
                txt = l.get('text', '') if isinstance(l, dict) else str(l)
                disc_m = re.search(r'(\d+)\s*%\s*off', txt, re.IGNORECASE)
                if disc_m:
                    discount_pct = float(disc_m.group(1))
                    if discount_pct > 0 and discount_pct < 100:
                        list_price = round(sell_price / (1 - (discount_pct / 100)), 2)
                        break
                        
            if list_price <= sell_price and sell_price > 0:
                # Estimativa base padrão de mercado caso o produto esteja em oferta
                list_price = round(sell_price * 1.25, 2)
                discount_pct = 20.0
                
            savings = round(list_price - sell_price, 2) if list_price > sell_price else 0.0
            available = True
            stock_qty = 999
            
            is_bug, bug_score, bug_reasons = classify_drogasil_bug(
                name, brand, list_price, sell_price, discount_pct, savings
            )
            
            clean_search = re.sub(r'[^\w\s]', ' ', name).strip()
            first_words = '+'.join(clean_search.split()[:4])
            
            comparison_urls = {
                'google_shopping': f"https://www.google.com.br/search?q={first_words}&tbm=shop",
                'buscape': f"https://www.buscape.com.br/search?q={first_words}"
            }
            
            prod_dict = {
                'id': f"droga_{sku}",
                'name': name,
                'brand': brand,
                'category': dept_name,
                'department': dept_name,
                'all_categories': [dept_name, cat_file.replace('.html', '')],
                'store': 'Drogasil',
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
            
        logger.info(f"Drogasil [{cat_file}]: {len(parsed_list)} produtos minerados com sucesso.")
        return parsed_list
    except Exception as e:
        logger.error(f"Erro ao minerar Drogasil {cat_file}: {e}")
        return []

def scan_drogasil_promos() -> list:
    """Varre todas as categorias da Drogasil em paralelo."""
    logger.info("Iniciando varredura paralela da Drogasil...")
    t0 = time.time()
    all_drog = []
    
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(fetch_drogasil_category, cat, dept)
            for cat, dept in DROGASIL_CATEGORIES
        ]
        for f in futures:
            try:
                res = f.result()
                if res:
                    all_drog.extend(res)
            except Exception as e:
                logger.warning(f"Erro em thread Drogasil: {e}")
                
    elapsed = round(time.time() - t0, 2)
    logger.info(f"Varredura Drogasil finalizada em {elapsed}s: {len(all_drog)} produtos capturados.")
    return all_drog
