import subprocess
import json
import re
import time
import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger('scanner_gazin')

GAZIN_CATEGORIES = [
    ('smartphones', 'Celulares e Smartphones'),
    ('informatica', 'Informática e PC Gamer'),
    ('eletrodomesticos', 'Eletrodomésticos'),
    ('moveis', 'Móveis e Decoração'),
    ('audio', 'Áudio e Caixas de Som'),
    ('ar-e-ventilacao', 'Ar e Ventilação'),
    ('eletroportateis', 'Eletroportáteis'),
    ('beleza-e-saude', 'Beleza e Saúde'),
    ('casa-e-jardim', 'Casa e Jardim'),
    ('brinquedos', 'Brinquedos e Bebês'),
    ('pneus', 'Automotivo e Pneus')
]

def get_current_build_id() -> str:
    default_build = 'Azwc7IX00Cp38BisSZRKI'
    try:
        res = subprocess.run(
            ['curl.exe', '-s', 'https://www.gazin.com.br/'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors='ignore',
            timeout=10
        )
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', res.stdout)
        if m:
            d = json.loads(m.group(1))
            return d.get('buildId', default_build)
    except Exception as e:
        logger.warning(f"Erro ao obter buildId do Gazin: {e}")
    return default_build

def classify_gazin_bug(name: str, brand: str, list_price: float, sell_price: float, discount_pct: float, savings: float):
    is_bug = False
    reasons = []
    score = 0
    name_lower = name.lower()
    
    if discount_pct >= 80:
        is_bug = True
        score += 85
        reasons.append(f"🔥 Desconto Brutal Gazin ({discount_pct:.1f}% OFF)")
    elif discount_pct >= 65:
        is_bug = True
        score += 65
        reasons.append(f"⚡ Super Desconto ({discount_pct:.1f}% OFF)")
    elif discount_pct >= 50:
        score += 35
        reasons.append(f"🏷️ Oferta Destaque ({discount_pct:.1f}% OFF)")

    # Eletrônicos ou Móveis caros por preço de centavos ou muito baixo
    if list_price >= 200.00 and sell_price <= 49.00 and sell_price > 0:
        is_bug = True
        score += 80
        reasons.append(f"💸 Erro de Preço/Centavos (R$ {sell_price:.2f} de R$ {list_price:.2f})")
        
    if savings >= 800.00 and discount_pct >= 45:
        is_bug = True
        score += 55
        reasons.append(f"💰 Economia Gigante (Economize R$ {savings:.2f})")
    elif savings >= 400.00 and discount_pct >= 40:
        score += 30
        reasons.append(f"💰 Grande Economia (R$ {savings:.2f})")
        
    final_score = max(0, min(100, score))
    return is_bug, final_score, reasons

def fetch_gazin_category(slug: str, dept_name: str, build_id: str) -> list:
    url = f"https://www.gazin.com.br/_next/data/{build_id}/categoria/{slug}.json?slug={slug}&sort=desconto"
    try:
        res = subprocess.run(
            ['curl.exe', '-s', url],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=12
        )
        if not res.stdout:
            return []
        d = json.loads(res.stdout)
        prods = d.get('pageProps', {}).get('conteudoProdutos', {}).get('products', [])
        
        parsed_list = []
        for p in prods:
            p_id = str(p.get('id') or '')
            if not p_id:
                continue
            name = p.get('name') or ''
            brand = p.get('brand') or 'Gazin'
            old_price = float(p.get('oldPrice') or 0.0)
            price = float(p.get('price') or 0.0)
            
            if old_price > price and price > 0:
                discount_pct = round(((old_price - price) / old_price) * 100, 1)
                savings = round(old_price - price, 2)
            else:
                discount_pct = 0.0
                savings = 0.0
                old_price = price
                
            img = p.get('images', {}).get('default') or ''
            raw_url = p.get('url') or ''
            link = f"https://www.gazin.com.br{raw_url}" if raw_url.startswith('/') else raw_url
            
            details = p.get('details') or {}
            ean_list = details.get('eanCode') or []
            ean = str(ean_list[0]).strip() if ean_list else ''
            
            is_bug, bug_score, bug_reasons = classify_gazin_bug(
                name, brand, old_price, price, discount_pct, savings
            )
            
            parsed_list.append({
                'id': f"gazin_{p_id}",
                'name': name,
                'brand': brand,
                'category': dept_name,
                'department': dept_name,
                'all_categories': [dept_name, 'Gazin'],
                'ean': ean,
                'store': 'Gazin',
                'link': link,
                'image': img,
                'list_price': round(old_price, 2),
                'sell_price': round(price, 2),
                'discount_pct': discount_pct,
                'savings': savings,
                'available': True,
                'stock_quantity': 10,
                'is_bug': is_bug,
                'bug_score': bug_score,
                'bug_reasons': bug_reasons
            })
        return parsed_list
    except Exception as e:
        logger.warning(f"Erro ao buscar categoria {slug} no Gazin: {e}")
        return []

def scan_gazin_promos() -> list:
    """Varre as principais categorias da Gazin em busca de descontos e bugs."""
    logger.info("Iniciando varredura no e-commerce da Gazin (www.gazin.com.br)...")
    build_id = get_current_build_id()
    logger.info(f"BuildId Gazin identificado: {build_id}")
    
    all_products = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [
            executor.submit(fetch_gazin_category, slug, dept, build_id)
            for slug, dept in GAZIN_CATEGORIES
        ]
        for f in futures:
            try:
                res = f.result()
                all_products.extend(res)
            except Exception as e:
                logger.debug(f"Falha em thread Gazin: {e}")
                
    logger.info(f"Total de produtos minerados da Gazin: {len(all_products)}")
    return all_products

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    items = scan_gazin_promos()
    print(f"Total coletado: {len(items)}")
    bugs = [p for p in items if p['is_bug'] or p['discount_pct'] >= 40]
    print(f"Promoções/Bugs com >= 40%: {len(bugs)}")
    for b in bugs[:5]:
        print(f" - [{b['store']}] {b['name'][:40]} | De: R$ {b['list_price']} ➔ R$ {b['sell_price']} (-{b['discount_pct']}% OFF)")
