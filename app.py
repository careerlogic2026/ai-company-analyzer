import streamlit as st
import google.generativeai as genai
import requests
from bs4 import BeautifulSoup
import PyPDF2
from io import BytesIO
from docx import Document
from tavily import TavilyClient
import time
from urllib.parse import urljoin

# --- 初期設定 ---
st.set_page_config(page_title="次世代企業分析AIエージェント", layout="wide")

# --- CSSでUIを整える ---
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; background-color: #007bff; color: white; }
    .source-card { background-color: white; padding: 15px; border-radius: 10px; border-left: 5px solid #007bff; margin-bottom: 10px; box-shadow: 2px 2px 5px rgba(0,0,0,0.05); }
    </style>
    """, unsafe_allow_html=True)

st.sidebar.title("🛠️ API設定")
gemini_key = st.sidebar.text_input("Gemini API Key", value=st.secrets.get("GEMINI_API_KEY", ""), type="password")
tavily_key = st.sidebar.text_input("Tavily API Key", value=st.secrets.get("TAVILY_API_KEY", ""), type="password")

if "step" not in st.session_state: st.session_state.step = 1
if "search_results" not in st.session_state: st.session_state.search_results = {}

# --- ツール関数 ---
def deep_read_content(url):
    """Web/PDFの全文抽出 + 1階層下のPDFも追跡"""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        if url.lower().endswith(".pdf"):
            res = requests.get(url, headers=headers, timeout=10)
            reader = PyPDF2.PdfReader(BytesIO(res.content))
            return "\n".join([p.extract_text() for p in reader.pages])[:15000]
        
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        soup = BeautifulSoup(res.content, 'html.parser')
        
        # 本文抽出 (広告などを除外)
        for s in soup(['script', 'style', 'nav', 'header', 'footer']): s.decompose()
        text = soup.get_text(separator='\n', strip=True)[:10000]
        
        # 1階層下のPDFリンクを1つだけ追跡
        pdf_text = ""
        for a in soup.find_all('a', href=True):
            if a['href'].lower().endswith('.pdf'):
                pdf_url = urljoin(url, a['href'])
                pdf_text = "\n【追加資料PDF】\n" + deep_read_content(pdf_url)
                break 
        return text + pdf_text
    except:
        return "[読み込み失敗]"

# ==========================================
# STEP 1: カテゴリ別検索
# ==========================================
if st.session_state.step == 1:
    st.title("🔍 高度企業分析: ソース収集")
    company = st.text_input("分析したい企業名を入力", placeholder="例：株式会社マクアケ")
    mandatory = st.text_area("📌 必ず読み込んでほしいURL（任意）")

    if st.button("🚀 最新情報をカテゴリ別にリサーチ"):
        if not gemini_key or not tavily_key:
            st.error("APIキーが必要です")
        else:
            tavily = TavilyClient(api_key=tavily_key)
            with st.spinner(f"{company} の情報を主要メディアから収集しています..."):
                # カテゴリ別の検索クエリ定義
                queries = {
                    "IR・財務": f"{company} (site:xj-storage.jp OR site:pronexus.co.jp OR site:nikkei.com) 決算資料 中期経営計画",
                    "PR・ニュース": f"{company} (site:prtimes.jp OR site:business.nikkei.com OR site:newspicks.com) 最新 プレスリリース",
                    "ヒト・社風": f"{company} (site:wantedly.com OR site:talentbook.jp OR site:note.com) 社員インタビュー 働き方"
                }
                
                results = {}
                for cat, q in queries.items():
                    resp = tavily.search(query=q, search_depth="advanced", max_results=5)
                    results[cat] = resp.get("results", [])
                
                st.session_state.search_results = results
                st.session_state.company = company
                st.session_state.mandatory_urls = [u.strip() for u in mandatory.split('\n') if u.strip()]
                st.session_state.step = 2
                st.rerun()

# ==========================================
# STEP 2: 視覚的なソース選択
# ==========================================
elif st.session_state.step == 2:
    st.title(f"✅ リサーチ対象の選定: {st.session_state.company}")
    st.write("各メディアから取得した候補です。AIに精読させたいものを選んでください。")

    selected_urls = []
    tabs = st.tabs(list(st.session_state.search_results.keys()))

    for i, cat in enumerate(st.session_state.search_results.keys()):
        with tabs[i]:
            for j, res in enumerate(st.session_state.search_results[cat]):
                with st.container():
                    st.markdown(f"""<div class='source-card'><b>{res['title']}</b><br><small>{res['url']}</small></div>""", unsafe_allow_html=True)
                    if st.checkbox("このソースを精読対象に含める", key=f"{cat}_{j}", value=(j<2)):
                        selected_urls.append(res['url'])

    if st.button("🧠 選択したソースで重厚な分析を開始"):
        st.session_state.selected_urls = selected_urls
        st.session_state.step = 3
        st.rerun()

# ==========================================
# STEP 3: コンサルタント級レポート生成
# ==========================================
elif st.session_state.step == 3:
    st.title("📊 最終分析レポート生成")
    all_urls = st.session_state.mandatory_urls + st.session_state.selected_urls
    
    with st.status("一次情報を精読・分析中...", expanded=True) as status:
        full_context = ""
        for url in all_urls:
            st.write(f"📖 読み込み中: {url}")
            full_context += f"\n--- SOURCE: {url} ---\n{deep_read_content(url)}\n"
        status.update(label="精読完了！レポートを執筆しています...", state="complete")

    # プロンプトの強化（戦略コンサルタントとしての推論を促す）
    genai.configure(api_key=gemini_key)
    model = genai.GenerativeModel('gemini-3.1-flash-lite-preview')
    
    prompt = f"""
    あなたは超一流のビジネスアナリスト兼キャリアコンサルタントです。
    提供された【最新の一次情報】を「点」として捉え、そこから読み取れる企業の「真の戦略」と「学生が描ける未来」を、圧倒的な熱量と文字数で論理的に構築してください。

    【一次情報（Web/PDFデータ）】
    {full_context}

    【レポートの構成要件】
    1. ビジネスモデルの核心（収益の仕組みを構造的に解説し、一次情報から読み取れる最新の戦略的転換点を指摘せよ）
    2. 競合優位性とSWOT分析（単なる事実の羅列ではなく、他社が真似できない「聖域」がどこにあるかを推論せよ）
    3. 実在の人物から読み解く組織文化（記事に登場する社員の言動から、この会社で評価される「共通のDNA」を言語化せよ）
    4. 3年後・30歳・40歳の市場価値（一次情報で示された成長戦略に基づき、この会社で得られるスキルが、他業界でどう評価されるか、具体的な転職・独立シナリオまで大胆に推論せよ）

    ※単なる情報の要約は厳禁。事実に裏打ちされた「大胆な考察（Gap Filling）」を各項目で展開すること。
    """

    with st.spinner("思考を整理し、未来を予測しています..."):
        response = model.generate_content(prompt)
        st.markdown(response.text)
        
        # Word出力
        doc = Document()
        doc.add_heading(f"{st.session_state.company} 徹底分析レポート", 0)
        doc.add_paragraph(response.text)
        bio = BytesIO(); doc.save(bio)
        st.download_button("📄 レポートをWordで保存", data=bio.getvalue(), file_name="Report.docx")

    if st.button("🔄 最初から"):
        st.session_state.step = 1
        st.rerun()
