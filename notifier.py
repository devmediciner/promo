import os
import json
import html
import requests
import logging

logger = logging.getLogger('promo_notifier')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')

DEFAULT_CONFIG = {
    "ntfy_topic": "promobug_devmediciner",
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "discord_webhook": "",
    "min_bug_score": 70,
    "ignore_medicines": True
}

def load_config() -> dict:
    config = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                config.update(saved)
        except Exception as e:
            logger.warning(f"Erro ao carregar config.json: {e}")
            
    # Permite sobrescrever com variáveis de ambiente se existirem
    if os.environ.get("NTFY_TOPIC"):
        config["ntfy_topic"] = os.environ.get("NTFY_TOPIC")
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        config["telegram_bot_token"] = os.environ.get("TELEGRAM_BOT_TOKEN")
    if os.environ.get("TELEGRAM_CHAT_ID"):
        config["telegram_chat_id"] = os.environ.get("TELEGRAM_CHAT_ID")
    if os.environ.get("DISCORD_WEBHOOK"):
        config["discord_webhook"] = os.environ.get("DISCORD_WEBHOOK")
        
    return config

def save_config(new_config: dict) -> dict:
    current = load_config()
    current.update(new_config)
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(current, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Erro ao salvar config.json: {e}")
    return current

def is_medicine_item(product: dict) -> bool:
    name = (product.get('name') or '').lower()
    dept = (product.get('department') or '').lower()
    cat = (product.get('category') or '').lower()
    
    if 'medicamento' in dept or 'medicamento' in cat:
        return True
    if 'saúde' in dept or 'saude' in dept:
        if not any(k in cat or k in name for k in ['suplemento', 'vitamina', 'proteína', 'whey']):
            return True
            
    pharma_words = [
        'comprimido', 'cápsula dura', 'capsula dura', 'genérico', 'generico', 
        'gotas ', 'xarope', 'posologia', 'tarja', 'anastrozol', 'imatinibe', 
        'letrozol', 'escitalopram', 'anlodipino', 'fluoxetina'
    ]
    if any(k in name for k in pharma_words):
        if not any(k in name for k in ['vitamina', 'suplemento', 'colágeno', 'creatina', 'whey']):
            return True
            
    return False

def send_promo_alert(product: dict, market_info: str = ""):
    """
    Envia notificação push com FOTO, LINK e PREÇO para Telegram, ntfy e Discord.
    """
    cfg = load_config()
    ntfy_topic = cfg.get("ntfy_topic", "").strip()
    tg_token = cfg.get("telegram_bot_token", "").strip()
    tg_chat = cfg.get("telegram_chat_id", "").strip()
    discord_webhook = cfg.get("discord_webhook", "").strip()
    
    title = f"🚨 PROMOBUG: {product.get('name', '')[:45]}"
    sell_price = product.get('sell_price', 0.0)
    list_price = product.get('list_price', 0.0)
    disc = product.get('discount_pct', 0.0)
    savings = product.get('savings', 0.0)
    link = product.get('link', '')
    brand = product.get('brand', 'Pague Menos')
    dept = product.get('department', 'Geral')
    stock = product.get('stock_quantity', 0)
    image_url = product.get('image', '').strip()
    
    # 1. TELEGRAM BOT COM FOTO, PREÇOS E BOTÃO DE COMPRA
    if tg_token and tg_chat:
        try:
            p_name_esc = html.escape(product.get('name', 'Produto'))
            brand_esc = html.escape(brand)
            dept_esc = html.escape(dept)
            
            caption_lines = [
                "🚨 <b>PROMOBUG DETECTADO NA PAGUE MENOS!</b> 🚨",
                f"🏷️ <b>{p_name_esc}</b>",
                f"🏢 <i>{brand_esc} • {dept_esc}</i>\n",
                f"💸 De: <s>R$ {list_price:.2f}</s>",
                f"🔥 <b>Por: R$ {sell_price:.2f} (-{disc:.1f}% OFF)</b>",
                f"💰 Economia de: <b>R$ {savings:.2f}</b>",
                f"📦 Estoque: <b>{stock} unidades disponíveis</b>"
            ]
            if market_info:
                caption_lines.append(f"\n🛡️ <b>Preço no Concorrente:</b> {html.escape(market_info)}")
                
            caption = "\n".join(caption_lines)
            
            # Botões inline no Telegram
            inline_keyboard = [
                [{"text": "🛒 Pegar Oferta na Pague Menos", "url": link}]
            ]
            comp_urls = product.get('comparison_urls') or {}
            if comp_urls.get('google_shopping'):
                inline_keyboard.append([
                    {"text": "🔍 Comparar no Google Shopping", "url": comp_urls['google_shopping']}
                ])
                
            reply_markup = {"inline_keyboard": inline_keyboard}

            # Tenta enviar com FOTO
            sent_photo = False
            if image_url and image_url.startswith("http"):
                try:
                    photo_endpoint = f"https://api.telegram.org/bot{tg_token}/sendPhoto"
                    r = requests.post(
                        photo_endpoint,
                        json={
                            "chat_id": tg_chat,
                            "photo": image_url,
                            "caption": caption,
                            "parse_mode": "HTML",
                            "reply_markup": reply_markup
                        },
                        timeout=8
                    )
                    if r.status_code == 200:
                        sent_photo = True
                        logger.info("PromoBug com foto enviado para o Telegram com sucesso!")
                except Exception as ex:
                    logger.debug(f"Falha ao enviar foto no Telegram, usando texto: {ex}")
                    
            if not sent_photo:
                # Fallback para mensagem de texto formatada
                text_endpoint = f"https://api.telegram.org/bot{tg_token}/sendMessage"
                requests.post(
                    text_endpoint,
                    json={
                        "chat_id": tg_chat,
                        "text": caption,
                        "parse_mode": "HTML",
                        "reply_markup": reply_markup,
                        "disable_web_page_preview": False
                    },
                    timeout=8
                )
                logger.info("PromoBug em texto enviado para o Telegram!")
        except Exception as e:
            logger.warning(f"Erro ao enviar para Telegram: {e}")

    # 2. NTFY.SH (Push para o celular)
    if ntfy_topic:
        try:
            msg_lines = [
                f"🏷️ {product.get('name')} ({brand})",
                f"💸 De: R$ {list_price:.2f} ➔ Por: R$ {sell_price:.2f} (-{disc:.1f}% OFF)",
                f"💰 Economia: R$ {savings:.2f}",
                f"📦 Estoque: {stock} unidades",
            ]
            if market_info:
                msg_lines.append(f"🛡️ Preço de Mercado: {market_info}")
            msg_lines.append(f"\n🛒 Link: {link}")
            
            headers = {
                "Title": title.encode('utf-8'),
                "Priority": "urgent",
                "Tags": "rotating_light,fire,dollar",
                "Click": link
            }
            if image_url and image_url.startswith("http"):
                headers["Attach"] = image_url
                
            requests.post(
                f"https://ntfy.sh/{ntfy_topic}",
                data="\n".join(msg_lines).encode('utf-8'),
                headers=headers,
                timeout=6
            )
        except Exception as e:
            logger.warning(f"Falha ao enviar via ntfy: {e}")

    # 3. DISCORD WEBHOOK
    if discord_webhook:
        try:
            embed = {
                "title": product.get('name'),
                "url": link,
                "color": 15548997,
                "fields": [
                    {"name": "Preço Original", "value": f"~~R$ {list_price:.2f}~~", "inline": True},
                    {"name": "Preço Bug", "value": f"**R$ {sell_price:.2f}**", "inline": True},
                    {"name": "Desconto", "value": f"**-{disc:.1f}% OFF**", "inline": True},
                    {"name": "Economia", "value": f"R$ {savings:.2f}", "inline": True},
                    {"name": "Estoque", "value": f"{stock} un.", "inline": True}
                ]
            }
            if image_url:
                embed["thumbnail"] = {"url": image_url}
            if market_info:
                embed["fields"].append({"name": "Preço de Mercado", "value": market_info, "inline": False})
                
            requests.post(
                discord_webhook,
                json={"content": "🚨 **PROMOBUG REAL DETECTADO NA PAGUE MENOS!**", "embeds": [embed]},
                timeout=6
            )
        except Exception as e:
            logger.warning(f"Falha ao enviar via Discord: {e}")

def send_test_notification(topic: str = "") -> dict:
    """Envia um alerta de teste via ntfy.sh."""
    cfg = load_config()
    target_topic = topic or cfg.get("ntfy_topic", "promobug_devmediciner")
    test_msg = "🔥 Alerta de Teste do PromoBug Radar!\n\nSeu celular está conectado e pronto para receber os melhores bugs de preço da Pague Menos em tempo real!"
    try:
        r = requests.post(
            f"https://ntfy.sh/{target_topic}",
            data=test_msg.encode('utf-8'),
            headers={
                "Title": "✅ PromoBug Radar Conectado!".encode('utf-8'),
                "Priority": "default",
                "Tags": "white_check_mark,bell"
            },
            timeout=5
        )
        if r.status_code == 200:
            return {"success": True, "message": f"Alerta enviado para ntfy.sh/{target_topic}!"}
        return {"success": False, "message": f"ntfy retornou status {r.status_code}"}
    except Exception as e:
        return {"success": False, "message": str(e)}

def send_test_telegram(token: str = "", chat_id: str = "") -> dict:
    """Envia mensagem e foto de teste para o Telegram do usuário."""
    cfg = load_config()
    t_token = token or cfg.get("telegram_bot_token", "").strip()
    t_chat = chat_id or cfg.get("telegram_chat_id", "").strip()
    
    if not t_token or not t_chat:
        return {"success": False, "message": "Preencha o Token do Bot e o Chat ID do Telegram!"}
        
    caption = (
        "🎉 <b>PromoBug Radar conectado com sucesso ao seu Telegram!</b>\n\n"
        "Quando um PromoBug for detectado, você receberá a foto, o preço De/Por, o desconto e o link direto para comprar antes de acabar o estoque!"
    )
    test_image = "https://paguemenos.vteximg.com.br/arquivos/ids/696662/7896902209046.jpg"
    
    try:
        photo_url = f"https://api.telegram.org/bot{t_token}/sendPhoto"
        r = requests.post(
            photo_url,
            json={
                "chat_id": t_chat,
                "photo": test_image,
                "caption": caption,
                "parse_mode": "HTML",
                "reply_markup": {
                    "inline_keyboard": [
                        [{"text": "🌐 Abrir Painel PromoRadar", "url": "https://github.com/devmediciner/promo"}]
                    ]
                }
            },
            timeout=8
        )
        if r.status_code == 200:
            return {"success": True, "message": "Mensagem e foto de teste enviadas para o Telegram!"}
        else:
            data = r.json()
            return {"success": False, "message": f"Erro do Telegram: {data.get('description', 'Token ou Chat ID inválido')}"}
    except Exception as e:
        return {"success": False, "message": str(e)}

def dispatch_bug_notifications(products: list, max_alerts: int = 3):
    """Varre a lista de produtos minerados e notifica os melhores PromoBugs."""
    cfg = load_config()
    min_score = cfg.get("min_bug_score", 70)
    ignore_meds = cfg.get("ignore_medicines", True)
    
    valid_bugs = []
    for p in products:
        if not p.get('is_bug') or not p.get('available'):
            continue
        if p.get('bug_score', 0) < min_score:
            continue
        if ignore_meds and is_medicine_item(p):
            continue
        valid_bugs.append(p)
        
    valid_bugs.sort(key=lambda x: (x.get('bug_score', 0), x.get('discount_pct', 0)), reverse=True)
    
    logger.info(f"Disparando notificações para até {min(max_alerts, len(valid_bugs))} bugs de destaque...")
    for p in valid_bugs[:max_alerts]:
        market_info = ""
        if p.get('market_verified'):
            market_info = f"{p.get('market_store')}: R$ {p.get('market_price'):.2f} (Economia real de R$ {p.get('real_savings'):.2f})"
        send_promo_alert(p, market_info)
