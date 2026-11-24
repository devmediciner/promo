import requests
import json
import os
import urllib.parse
import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger('price_checker')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(BASE_DIR, 'data', 'price_cache.json')
os.makedirs(os.path.join(BASE_DIR, 'data'), exist_ok=True)

# Memória cache de consultas para não repetir requisições
_cache = {}

def load_cache():
    global _cache
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                _cache = json.load(f)
        except Exception:
            _cache = {}

def save_cache():
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(_cache, f, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Erro ao salvar cache de preços: {e}")

load_cache()

def get_comparison_urls(name: str, ean: str = "") -> dict:
    """Gera links diretos para comparação de preço no Google Shopping e Buscapé."""
    query = ean if (ean and len(ean) >= 8 and ean.isdigit()) else name
    query_encoded = urllib.parse.quote_plus(query)
    name_encoded = urllib.parse.quote_plus(name)
    
    return {
        "google_shopping": f"https://www.google.com.br/search?q={query_encoded}&tbm=shop",
        "buscape": f"https://www.buscape.com.br/search?q={query_encoded if ean else name_encoded}",
        "epoca_cosmeticos": f"https://www.epocacosmeticos.com.br/busca?ft={query_encoded}"
    }

def check_epoca_cosmeticos(ean: str) -> dict:
    """
    Consulta o catálogo da Época Cosméticos via API pública VTEX usando o EAN.
    Retorna os dados do produto concorrente se encontrado.
    """
    if not ean or len(ean) < 8 or not ean.isdigit():
        return None
        
    url = f"https://www.epocacosmeticos.com.br/api/catalog_system/pub/products/search?ft={ean}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'application/json'
    }
    
    try:
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code in [200, 206]:
            data = r.json()
            if isinstance(data, list) and len(data) > 0:
                p = data[0]
                items = p.get('items', [])
                if items:
                    item = items[0]
                    sellers = item.get('sellers', [])
                    if sellers:
                        comm = sellers[0].get('commertialOffer', {})
                        price = float(comm.get('Price') or 0.0)
                        list_price = float(comm.get('ListPrice') or 0.0)
                        final_price = price if price > 0 else list_price
                        if final_price > 0:
                            return {
                                "store": "Época Cosméticos",
                                "product_name": p.get('productName', ''),
                                "price": round(final_price, 2),
                                "link": p.get('link', '')
                            }
    except Exception as e:
        logger.debug(f"Falha ao consultar Época Cosméticos para EAN {ean}: {e}")
        
    return None

def verify_market_price(product: dict) -> dict:
    """
    Analisa se o produto possui preço comprovado em concorrentes.
    Retorna métricas de validação de PromoBug real.
    """
    ean = str(product.get('ean') or '').strip()
    name = product.get('name') or ''
    sell_price = float(product.get('sell_price') or 0.0)
    
    comp_urls = get_comparison_urls(name, ean)
    
    market_info = {
        "ean": ean,
        "market_verified": False,
        "market_store": "",
        "market_price": 0.0,
        "market_link": "",
        "real_savings": 0.0,
        "real_discount_pct": 0.0,
        "comparison_urls": comp_urls
    }
    
    if not ean or len(ean) < 8 or not ean.isdigit() or sell_price <= 0:
        return market_info
        
    # Checagem em Cache
    if ean in _cache:
        cached = _cache[ean]
        if cached.get("found"):
            market_price = cached.get("price", 0.0)
            if market_price > sell_price:
                real_savings = round(market_price - sell_price, 2)
                real_discount = round(((market_price - sell_price) / market_price) * 100, 1)
                market_info.update({
                    "market_verified": True,
                    "market_store": cached.get("store", "Concorrente"),
                    "market_price": market_price,
                    "market_link": cached.get("link", ""),
                    "real_savings": real_savings,
                    "real_discount_pct": real_discount
                })
        return market_info

    # Consulta ao vivo concorrente (Época Cosméticos)
    competitor = check_epoca_cosmeticos(ean)
    if competitor:
        market_price = competitor["price"]
        _cache[ean] = {
            "found": True,
            "store": competitor["store"],
            "price": market_price,
            "link": competitor["link"]
        }
        if market_price > sell_price:
            real_savings = round(market_price - sell_price, 2)
            real_discount = round(((market_price - sell_price) / market_price) * 100, 1)
            # Considerado PromoBug Real se for pelo menos 25% mais barato que o preço praticado no concorrente
            is_verified = (real_discount >= 25.0)
            market_info.update({
                "market_verified": is_verified,
                "market_store": competitor["store"],
                "market_price": market_price,
                "market_link": competitor["link"],
                "real_savings": real_savings,
                "real_discount_pct": real_discount
            })
    else:
        _cache[ean] = {"found": False}
        
    return market_info

def enrich_products_with_market_data(products: list, max_checks: int = 40) -> list:
    """
    Enriquece a lista de produtos com URLs comparativas e checa o preço de mercado
    priorizando os itens marcados como PromoBug ou com maiores descontos.
    """
    # 1. Adiciona URLs de comparação em todos os produtos
    for p in products:
        ean = str(p.get('ean') or '').strip()
        p['comparison_urls'] = get_comparison_urls(p.get('name', ''), ean)
        p['market_verified'] = False
        p['market_store'] = ''
        p['market_price'] = 0.0
        p['real_savings'] = 0.0
        p['real_discount_pct'] = 0.0
        
    # 2. Seleciona os melhores candidatos a PromoBug para verificação de mercado
    candidates = [
        p for p in products 
        if p.get('is_bug') or p.get('discount_pct', 0) >= 70
    ][:max_checks]
    
    if not candidates:
        return products
        
    logger.info(f"Verificando preço de mercado para {len(candidates)} produtos candidatos a PromoBug...")
    
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(verify_market_price, p): p for p in candidates}
        for fut in futures:
            try:
                p = futures[fut]
                minfo = fut.result()
                if minfo.get('market_verified'):
                    p['market_verified'] = True
                    p['market_store'] = minfo['market_store']
                    p['market_price'] = minfo['market_price']
                    p['market_link'] = minfo.get('market_link', '')
                    p['real_savings'] = minfo['real_savings']
                    p['real_discount_pct'] = minfo['real_discount_pct']
                    
                    # Adiciona motivo com preço de mercado comprovado
                    p['bug_reasons'] = [
                        f"🛡️ Preço Real Confirmado ({p['market_store']}: R$ {p['market_price']:.2f})"
                    ] + [r for r in p.get('bug_reasons', []) if 'Confirmado' not in r]
                    p['bug_score'] = min(100, (p.get('bug_score', 50) + 20))
            except Exception as e:
                logger.debug(f"Erro ao verificar produto concorrente: {e}")
                
    save_cache()
    return products
