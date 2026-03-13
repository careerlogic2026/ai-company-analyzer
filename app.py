import streamlit as st
import google.generativeai as genai
import requests
from bs4 import BeautifulSoup
import PyPDF2
from io import BytesIO
from docx import Document
from tavily import TavilyClient
import time
from urllib.parse import urljoin, urlparse

# --- 初期設定 ---
st.set_page_config(page_title="プロフェッショナル企業分析AI", layout="wide")

st.sidebar.title("🛠️ API設定")
gemini_key = st.sidebar.text_input("Gemini API Key", value=st.secrets.get("GEMINI_API_KEY", ""), type="password")
tavily_key = st.sidebar.text_input("Tavily API Key", value=st.secrets.get("TAVILY_API_KEY", ""), type="password")

if "step" not in st.session_state: st.session_state.step = 1

# --- ツール関数：URLからリンクを抽出してフィルタリング ---
def get_sub_links(base_url, keywords, limit=5):
    """特定のキーワードを含むリンクをページ内から抽出"""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(base_url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.content, 'html.parser')
        links = []
        for a in soup.find_all('a', href=True):
            url = urljoin(base_url, a['href'])
            text = a.get_text().lower()
            # 指定したキーワードのいずれかがテキストかURLに含まれているかチェック
            if any(k in text or k in url.lower() for k in keywords):
                if url not in links and urlparse(url).netloc == urlparse(base_url).netloc:
                    links.append({"title": a.get_text().strip() or url, "url": url})
            if len(links) >= limit: break
        return links
    except:
        return []

def deep_read_content(url):
    """Web/PDFの全文抽出"""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        if url.lower().endswith(".pdf"):
            res = requests.get(url, headers=headers, timeout=10)
            reader = PyPDF2.PdfReader(BytesIO(res.content))
            return "\n".join([p.extract_text() for p in reader.pages])[:15000]
        
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        soup = BeautifulSoup(res.content, 'html.parser')
        for s in soup(['script', 'style', 'nav', 'header', 'footer']): s.decompose()
        return soup.get_text(separator='\n', strip=True)[:10000]
    except:
        return "[読み込み失敗]"

# ==========================================
# STEP 1: 起点となる情報の入力
# ==========================================
if st.session_state.step == 1:
    st.title("🎯 Step 1: 分析起点の指定")
    st.info("企業URLを入力することで、そのドメイン内のIRやニュースを正確に捕捉します。")
    
    col1, col2 = st.columns(2)
    with col1:
        company = st.text_input("企業名", placeholder="例：株式会社マクアケ")
        hp_url = st.text_input("公式HP URL", placeholder="https://www.makuake.co.jp/")
    with col2:
        pr_url = st.text_input("PR TIMES 企業ページ (任意)", placeholder="https://prtimes.jp/main/html/searchrl/company_id/12345")
        rec_url = st.text_input("採用/Wantedly ページ (任意)", placeholder="https://www.wantedly.com/companies/makuake")

    if st.button("🔍 ポータル内から最新ソースを抽出"):
        if not gemini_key or not tavily_key:
            st.error("APIキーを設定してください")
        elif not company or not hp_url:
            st.error("企業名と公式HPのURLは必須です")
        else:
            with st.spinner("各サイトから最新の個別記事・IR資料のリンクを抽出中..."):
                results = {}
                
                # 1. 公式サイトからIR資料を自動探索
                results["IR・経営"] = get_sub_links(hp_url, ["ir", "investor", "settlement", "pdf", "kessan"], limit=5)
                
                # 2. PR TIMESがあればそこから最新記事を、なければ検索
                if pr_url:
                    results["最新ニュース"] = get_sub_links(pr_url, ["main/html/rd"], limit=5)
                else:
                    tavily = TavilyClient(api_key=tavily_key)
                    q_res = tavily.search(query=f"{company} site:prtimes.jp", max_results=5)
                    results["最新ニュース"] = [{"title": r['title'], "url": r['url']} for r in q_res.get("results", [])]
                
                # 3. 採用・ヒト情報
                if rec_url:
                    results["採用・ヒト"] = get_sub_links(rec_url, ["story", "post", "interview", "articles"], limit=5)
                else:
                    tavily = TavilyClient(api_key=tavily_key)
                    q_res = tavily.search(query=f"{company} site:wantedly.com OR site:note.com インタビュー", max_results=5)
                    results["採用・ヒト"] = [{"title": r['title'], "url": r['url']} for r in q_res.get("results", [])]

                st.session_state.search_results = results
                st.session_state.company = company
                st.session_state.step = 2
                st.rerun()

# ==========================================
# STEP 2: 精読対象の確定
# ==========================================
elif st.session_state.step == 2:
    st.title(f"📖 ソースの選択: {st.session_state.company}")
    st.write("各ポータルサイトから抽出された個別リンクです。これらを「全文」精読します。")

    selected_urls = []
    tabs = st.tabs(list(st.session_state.search_results.keys()))

    for i, cat in enumerate(st.session_state.search_results.keys()):
        with tabs[i]:
            if not st.session_state.search_results[cat]:
                st.warning("有効なリンクが見つかりませんでした。")
            for j, item in enumerate(st.session_state.search_results[cat]):
                st.markdown(f"**{item['title']}**")
                st.caption(item['url'])
                if st.checkbox("この個別ページを精読する", key=f"{cat}_{j}", value=True):
                    selected_urls.append(item['url'])
                st.markdown("---")

    if st.button("🚀 選択した全ページを精読してレポート生成"):
        st.session_state.selected_urls = selected_urls
        st.session_state.step = 3
        st.rerun()

# ==========================================
# STEP 3: レポート生成（前回の強化プロンプトを維持）
# ==========================================
elif st.session_state.step == 3:
    # (Step 3の内容は、前回の「戦略コンサルタントプロンプト」をそのまま使用)
    st.title("📊 ディープリサーチレポート生成")
    
    with st.status("一次情報を精読中...", expanded=True) as status:
        full_context = ""
        for url in st.session_state.selected_urls:
            st.write(f"📖 全文読み込み中: {url}")
            full_context += f"\n--- SOURCE: {url} ---\n{deep_read_content(url)}\n"
        status.update(label="精読完了！", state="complete")

    genai.configure(api_key=gemini_key)
    model = genai.GenerativeModel('gemini-3.1-flash-lite-preview')
    
    # プロンプトは前回の「推論重視」のものを適用
    prompt = f"対象企業: {st.session_state.company}\n\n一次情報:\n{full_context}\n\n" + \
             "あなたは一流のビジネスアナリストです。提供された一次情報に基づき、" + \
             "単なる要約ではなく、背景にある戦略や30歳時点の市場価値まで大胆に推論し、" + \
             "圧倒的なボリュームでレポートを作成してください。"

    with st.spinner("分析中..."):
        response = model.generate_content(prompt)
        st.markdown(response.text)
        
        doc = Document()
        doc.add_heading(f"{st.session_state.company} レポート", 0)
        doc.add_paragraph(response.text)
        bio = BytesIO(); doc.save(bio)
        st.download_button("📄 Word保存", data=bio.getvalue(), file_name="Report.docx")
