# 🏷️ Pague Menos PromoRadar & Caçador de PromoBugs (Geral - Site Inteiro)

Painel web de alta performance desenvolvido para monitorar em tempo real e filtrar as melhores oportunidades e **PromoBugs** de **todo o site oficial da Pague Menos**, cobrindo todas as categorias:
- ✨ **Dermo e Beleza** (Rosto, Cabelos, Corpo, Perfumaria Importada, Protetores Solares, Maquiagem)
- 💊 **Medicamentos e Saúde** (Genéricos, Controlados, Primeiros Socorros)
- 🧴 **Higiene Pessoal** (Cuidados Orais, Sabonetes, Desodorantes)
- 👶 **Mamães e Bebês** (Fraldas descartáveis, Fórmulas, Acessórios)
- 🥗 **Vida Saudável** (Suplementos, Whey Protein, Vitaminas)

---

## ⚡ Como Rodar no Computador (Local)

Dê dois cliques no arquivo:
```
iniciar.bat
```
Ou pelo terminal:
```bash
python main.py
```
O navegador abrirá automaticamente em: **[http://localhost:8000](http://localhost:8000)**.

---

## 🔄 Ele atualiza sozinho?

**SIM!** O sistema agora conta com **3 níveis de atualização automática**:

1. **Auto-Scan em Segundo Plano no Servidor (10 em 10 minutos):**
   - Assim que o aplicativo inicia, uma tarefa de segundo plano (`background_scheduler_loop`) roda 24/7 sem travar a interface.
   - A cada 10 minutos (configurável), ele varre novamente todas as categorias da Pague Menos e atualiza o banco de dados `promos.db`.
2. **Atualização Dinâmica na Tela do Navegador:**
   - A cada 60 segundos, o painel web sincroniza silenciosamente os dados com o servidor sem que você precise recarregar a página (`F5`).
3. **Botão de Varredura Sob Demanda:**
   - O botão `⚡ Escanear Agora` no topo permite disparar uma nova varredura a qualquer momento com feedback visual.

---

## 🌐 Como colocar Online 24/7 de Graça (Deploy via GitHub)

O GitHub por si só é um repositório de código (não hospeda servidores Python com banco rodando 24h direto), **mas você pode colocá-lo online 100% grátis e automático conectando seu GitHub a uma plataforma de nuvem**:

### Opção 1: Render.com (Recomendado - 100% Grátis)
1. Suba esta pasta para um repositório no seu GitHub.
2. Crie uma conta gratuita em [render.com](https://render.com).
3. Clique em **New +** > **Web Service**.
4. Conecte o repositório que você acabou de criar no GitHub.
5. O Render detectará automaticamente o arquivo `render.yaml` e `requirements.txt` que já deixamos configurados!
6. Clique em **Deploy Web Service**.
7. Pronto! Você ganha um link público permanente (ex: `https://meu-promoradar.onrender.com`) que fica rodando na nuvem 24 horas por dia, atualizando sozinho e acessível pelo celular!

### Opção 2: GitHub Actions (Automação Nativa)
Já deixamos configurado o arquivo [`.github/workflows/scanner.yml`](.github/workflows/scanner.yml).
- A cada 30 minutos, os servidores do GitHub executam o `scanner.py` automaticamente e salvam o banco de dados atualizado no repositório.

---

## 📂 Arquivos do Projeto

- `main.py`: Inicializador inteligente que detecta portas livres e abre o navegador.
- `app.py`: Servidor FastAPI com agendador de segundo plano (auto-scan a cada 10 min).
- `scanner.py`: Varredor paralelo multi-departamento (34 requisições simultâneas em ~7 segundos).
- `database.py`: Banco de dados SQLite com transações em lote.
- `templates/index.html`: Dashboard com tema escuro, filtros de departamento, cópia rápida para WhatsApp e alertas.
- `requirements.txt` & `Procfile`: Dependências e comando de inicialização para servidores em nuvem.
- `iniciar.bat`: Executável com um clique para Windows.
