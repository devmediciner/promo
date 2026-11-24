import requests
import json
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from database import init_db, bulk_upsert_products, log_scan

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('promo_scanner')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
}

PREMIUM_BRANDS = [
    'calvin klein', 'giorgio armani', 'yves saint laurent', 'la roche-posay', 'la roche posay',
    'vichy', 'cerave', 'bioderma', 'skinceuticals', 'avène', 'avene', 'eucerin', 'isdin',
    'l\'oréal professionnel', 'loreal professionnel', 'sebastian professional', 'wella',
    'kérastase', 'kerastase', 'rochas', 'azzaro', 'paco rabanne', 'carolina herrera',
    'dior', 'chanel', 'lancôme', 'lancome', 'clinique', 'shiseido', 'nars', 'mac',
    'pampers', 'huggies', 'growth', 'max titanium', 'integralmedica', 'optimum nutrition'
]

# Principais Departamentos da Pague Menos
DEPARTMENTS = {
    '100': 'Medicamentos e Saúde',
    '200': 'Higiene Pessoal',
    '300': 'Dermo e Beleza',
    '400': 'Mamães e Bebês',
    '500': 'Vida Saudável',
    '600': 'Conveniência',
    '610': 'Pet shop'
}

def classify_bug(prod_name: str, brand: str, list_price: float, sell_price: float, discount_pct: float, savings: float, stock_qty: int):
    """
    Classifica se o produto é um 'PromoBug' e calcula score e tags.
    """
    is_bug = False
    reasons = []
    score = 0
    name_lower = prod_name.lower()
    brand_lower = (brand or '').lower()
    is_premium = any(pb in brand_lower or pb in name_lower for pb in PREMIUM_BRANDS)
    
    # 1. Erro de cadastro / Teste
    if 'teste' in name_lower:
        is_bug = True
        score += 90
        reasons.append('⚠️ Item de Teste em Produção')
        
    # 2. Desconto extremo (90%+)
    if discount_pct >= 90:
        is_bug = True
        score += 85
        reasons.append(f'🔥 Desconto Brutal ({discount_pct:.1f}% OFF)')
    elif discount_pct >= 80:
        is_bug = True
        score += 65
        reasons.append(f'⚡ Desconto Extremo ({discount_pct:.1f}% OFF)')
    elif discount_pct >= 70:
        score += 40
        reasons.append(f'🏷️ Super Promoção ({discount_pct:.1f}% OFF)')
        
    # 3. Bug em Marca Premium / Perfumaria Importada / Fraldas Premium
    if is_premium and discount_pct >= 65:
        is_bug = True
        score += 50
        reasons.append(f'💎 Grife/Marca Premium ({brand})')
    elif is_premium and discount_pct >= 50:
        score += 25
        
    # 4. Erro de centavos ou preço irrealmente baixo
    if sell_price > 0 and sell_price <= 4.00 and list_price >= 20.00:
        is_bug = True
        score += 70
        reasons.append(f'💸 Preço de Centavos (R$ {sell_price:.2f} de R$ {list_price:.2f})')
        
    # 5. Queda extrema de preço absoluto (economia brutal)
    if savings >= 200.00 and discount_pct >= 70:
        is_bug = True
        score += 55
        reasons.append(f'💰 Economia Gigante (Economize R$ {savings:.2f})')
    elif savings >= 100.00 and discount_pct >= 70:
        is_bug = True
        score += 40
        reasons.append(f'💰 Grande Economia (Economize R$ {savings:.2f})')
        
    # 6. Despencou de valor alto para baixo
    if list_price >= 150.00 and sell_price <= 35.00:
        is_bug = True
        score += 60
        reasons.append(f'📉 Queda Abrupta de Patamar de Preço')
        
    # Bonificação por estoque
    if is_bug and stock_qty > 0:
        score += 15
        if stock_qty >= 50:
            reasons.append(f'📦 Estoque Alto Disponível ({stock_qty} un)')
        else:
            reasons.append(f'⚡ Disponível para Compra ({stock_qty} un)')
    elif is_bug and stock_qty == 0:
        score -= 20
        reasons.append('⏳ Esgotado no Momento')
        
    final_score = max(0, min(100, score))
    return is_bug, final_score, reasons

def parse_catalog_product(p: dict):
    try:
        p_id = str(p.get('productId') or '')
        name = p.get('productName') or ''
        brand = p.get('brand') or ''
        link = p.get('link') or ''
        if link and not link.startswith('http'):
            link = 'https://www.paguemenos.com.br' + ('/' if not link.startswith('/') else '') + link
            
        categories = p.get('categories') or []
        main_cat = 'Geral'
        department = 'Outros'
        if categories:
            parts = [c.strip('/') for c in categories[0].split('/') if c.strip('/')]
            if len(parts) >= 1:
                department = parts[0]
                main_cat = parts[-1] if len(parts) > 1 else parts[0]
                
        items = p.get('items') or []
        if not items:
            return None
            
        item = items[0]
        image = ''
        images = item.get('images') or []
        if images:
            image = images[0].get('imageUrl') or ''
            
        sellers = item.get('sellers') or []
        if not sellers:
            return None
            
        comm = sellers[0].get('commertialOffer') or {}
        list_price = float(comm.get('ListPrice') or 0.0)
        sell_price = float(comm.get('Price') or 0.0)
        stock_qty = int(comm.get('AvailableQuantity') or 0)
        available = stock_qty > 0
        
        if sell_price == 0 and comm.get('spotPrice'):
            sell_price = float(comm.get('spotPrice'))
            
        if list_price and list_price > sell_price and sell_price > 0:
            discount_pct = round(((list_price - sell_price) / list_price) * 100, 1)
            savings = round(list_price - sell_price, 2)
        else:
            discount_pct = 0.0
            savings = 0.0
            
        is_bug, bug_score, bug_reasons = classify_bug(
            name, brand, list_price, sell_price, discount_pct, savings, stock_qty
        )
        
        return {
            'id': p_id,
            'name': name,
            'brand': brand,
            'category': main_cat,
            'department': department,
            'all_categories': categories,
            'link': link,
            'image': image,
            'list_price': round(list_price, 2),
            'sell_price': round(sell_price, 2),
            'discount_pct': discount_pct,
            'savings': savings,
            'available': available,
            'stock_quantity': stock_qty,
            'is_bug': is_bug,
            'bug_score': bug_score,
            'bug_reasons': bug_reasons
        }
    except Exception as e:
        logger.error(f"Error parsing product {p.get('productId')}: {e}")
        return None

def fetch_url(url: str):
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        if r.status_code in [200, 206]:
            return r.json()
    except Exception as e:
        logger.warning(f"Request failed for {url}: {e}")
    return None

def run_full_scan():
    """
    Executa varredura profunda no catálogo da Pague Menos cobrindo:
    1. O SITE INTEIRO por ordem de Maior Desconto (top ofertas globais)
    2. O SITE INTEIRO por Preço Crescente (erros de centavos, R$ 0.01 a R$ 3.00)
    3. Cada Departamento Principal (Dermo & Beleza, Medicamentos, Higiene, Bebês, Suplementos)
    4. Subcategorias Chave de Perfumaria, Skincare, Cabelos, Protetor Solar
    5. Intelligent Search Global
    """
    init_db()
    t_start = time.time()
    urls_to_scan = []
    
    # 1. SITE INTEIRO - Maiores Descontos Globais (sem restrição de categoria)
    for f in [0, 50, 100, 150, 200, 250]:
        urls_to_scan.append(
            f'https://www.paguemenos.com.br/api/catalog_system/pub/products/search?O=OrderByBestDiscountDESC&_from={f}&_to={f+49}'
        )
        
    # 2. SITE INTEIRO - Menores Preços Globais (Caça Bugs de centavos)
    for f in [0, 50, 100]:
        urls_to_scan.append(
            f'https://www.paguemenos.com.br/api/catalog_system/pub/products/search?O=OrderByPriceASC&_from={f}&_to={f+49}'
        )
        
    # 3. Departamentos Principais por Desconto
    for dept_id in DEPARTMENTS.keys():
        urls_to_scan.append(
            f'https://www.paguemenos.com.br/api/catalog_system/pub/products/search?fq=C:{dept_id}&O=OrderByBestDiscountDESC&_from=0&_to=49'
        )
        urls_to_scan.append(
            f'https://www.paguemenos.com.br/api/catalog_system/pub/products/search?fq=C:{dept_id}&O=OrderByBestDiscountDESC&_from=50&_to=99'
        )

    # 4. Subcategorias Críticas de Dermo e Beleza (alta ocorrência de promoções de perfumes e dermocosméticos)
    subcats = [
        'C:300/302/',  # Rosto
        'C:300/303/',  # Cabelos
        'C:300/301/',  # Corpo
        'C:300/879/',  # Perfumes e Colônias
        'C:300/305/',  # Protetores Solares Corporais
        'C:300/306/',  # Protetores Solares Faciais
        'C:300/882/',  # Maquiagem
    ]
    for sub in subcats:
        urls_to_scan.append(
            f'https://www.paguemenos.com.br/api/catalog_system/pub/products/search?fq={sub}&O=OrderByBestDiscountDESC&_from=0&_to=49'
        )

    # 5. Intelligent Search para pegar promoções relâmpago de todo o site
    for p in [1, 2, 3, 4]:
        urls_to_scan.append(
            f'https://www.paguemenos.com.br/_v/api/intelligent-search/product_search?sort=discount:desc&count=50&page={p}'
        )

    logger.info(f"Iniciando varredura em todo o site com {len(urls_to_scan)} requisições simultâneas...")
    
    raw_products = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_url = {executor.submit(fetch_url, url): url for url in urls_to_scan}
        for future in as_completed(future_to_url):
            data = future.result()
            if not data:
                continue
            if isinstance(data, list):
                raw_products.extend(data)
            elif isinstance(data, dict) and 'products' in data:
                raw_products.extend(data['products'])

    logger.info(f"Total bruto de produtos coletados do site: {len(raw_products)}")
    
    # Process and upsert in bulk
    processed_ids = set()
    products_to_save = []
    total_promos = 0
    total_bugs = 0
    
    for rp in raw_products:
        parsed = parse_catalog_product(rp)
        if not parsed or not parsed['id']:
            continue
        if parsed['id'] in processed_ids:
            continue
        processed_ids.add(parsed['id'])
        products_to_save.append(parsed)
        
        if parsed['discount_pct'] >= 70:
            total_promos += 1
        if parsed['is_bug']:
            total_bugs += 1

    bulk_upsert_products(products_to_save)
    total_saved = len(products_to_save)
    duration = round(time.time() - t_start, 2)
    log_scan(total_saved, total_promos, total_bugs, duration, "SUCCESS")
    logger.info(f"Varredura global concluída em {duration}s! Total únicos: {total_saved} | Descontos >= 70%: {total_promos} | PromoBugs: {total_bugs}")
    
    return {
        'total_scanned': total_saved,
        'total_promos': total_promos,
        'total_bugs': total_bugs,
        'duration_seconds': duration
    }

if __name__ == '__main__':
    res = run_full_scan()
    print("Resultado da Varredura:", res)
