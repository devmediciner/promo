import uvicorn
import os
import sys
import socket
import webbrowser
import threading
import time

def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def open_browser(port: int):
    time.sleep(1.2)
    url = f"http://localhost:{port}"
    try:
        webbrowser.open(url)
    except Exception:
        pass

if __name__ == '__main__':
    # Ensure current directory is on python path
    base_dir = os.path.dirname(os.path.abspath(__file__))
    if base_dir not in sys.path:
        sys.path.insert(0, base_dir)
    os.chdir(base_dir)

    port = int(os.environ.get("PORT", 8000))
    if is_port_in_use(port):
        print(f"Porta {port} ja esta em uso. Tentando porta {port + 1}...")
        port += 1

    print(f"\n=======================================================")
    print(f"🔥 PAGUE MENOS PROMORADAR - PAINEL WEB INICIADO! 🔥")
    print(f"Acesse no navegador: http://localhost:{port}")
    print(f"=======================================================\n")
    
    # Abrir navegador automaticamente
    threading.Thread(target=open_browser, args=(port,), daemon=True).start()
    
    uvicorn.run("app:app", host="127.0.0.1", port=port, reload=False)
