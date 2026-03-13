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
st.set_page_config(page_title="高度企業分析AI (Human-in-the-Loop版)", layout="wide")
st.sidebar.title("🛠️ 設定")
gemini_api_key = st.sidebar.text_input("Gemini API Key", value=st.secrets.get("GEMINI_API_KEY", ""), type="password")
tavily_api_key = st.sidebar.text_input("Tavily API Key", value=st.secrets.get("TAVILY_API_KEY", ""), type="password")

# --- 状態管理 (画面遷移用) ---
if "step" not in st.session_state:
    st.session_state.step = 1
if "candidates" not in st.session_state:
    st.session_state.candidates = []
if "company_name" not in st.session_state:
    st.session_state.company_name = ""

# --- ツール関数：PDFとWebの深掘り読み込み ---
def read_pdf_from_url(url):
    """PDFをダウンロードしてテキストを抽出"""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        reader = PyPDF2.PdfReader(BytesIO(response.content))
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text[:10000] # 長すぎる場合は1万文字でカット
    except Exception as e:
        return f"[PDF読み込み失敗: {url} ({e})]"

def deep_read_url(url):
    """Webページを読み込み、さらに1階層目のPDFリンクも探して読む"""
    if url.lower().endswith(".pdf"):
        return read_pdf_from_url(url)
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # 1. 本文の抽出
        main_text = soup.get_text(separator='\n', strip=True)[:10000]
        result_text = f"【本文】\n{main_text}\n"
        
        # 2. 1階層目のPDFリンクを探して読む（最大2個まで：無限ループ防止）
        pdf_links = []
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            if href.lower().endswith('.pdf'):
                full_url = urljoin(url, href)
                if full_url not in pdf_links:
                    pdf_links.append(full_url)
                    
        for i, pdf_url in enumerate(pdf_links[:2]):
            result_text += f"\n【関連PDFデータ({i+1})】\n{read_pdf_from_url(pdf_url)}\n"
            
        return result_text
    except Exception as e:
        return f"[Web読み込み失敗: {url} ({e})]"

# ==========================================
# UI ステップ1：入力とソース検索
# ==========================================
if st.session_state.step == 1:
    st.title("🔍 Step 1: 企業名と事前情報の入力")
    
    company_name = st.text_input("分析したい企業名（例：株式会社マクアケ）")
    mandatory_urls = st.text_area("📌 必ずリサーチしてほしいURL（1行に1つ）\n例：公式IRページのURLや、読んでほしいプレスリリースのURL")
    
    if st.button("🌐 高精度ソース候補を検索する"):
        if not gemini_api_key or not tavily_api_key:
            st.error("サイドバーにAPIキーを設定してください。")
        elif not company_name:
            st.error("企業名を入力してください。")
        else:
            st.session_state.company_name = company_name
            st.session_state.mandatory_urls = [u.strip() for u in mandatory_urls.split('\n') if u.strip()]
            
            with st.spinner("Tavily AIが最新のIR、ニュース、インタビュー候補を収集中..."):
                try:
                    tavily_client = TavilyClient(api_key=tavily_api_key)
                    # 企業に関するIR・採用・ニュースをまとめて検索
                    query = f"{company_name} 決算資料 OR 中期経営計画 OR 採用インタビュー OR 最新ニュース"
                    response = tavily_client.search(query=query, search_depth="advanced", max_results=10)
                    
                    st.session_state.candidates = response.get("results", [])
                    st.session_state.step = 2
                    st.rerun()
                except Exception as e:
                    st.error(f"検索エラー: {e}")

# ==========================================
# UI ステップ2：ソースの選択
# ==========================================
elif st.session_state.step == 2:
    st.title("✅ Step 2: リサーチ対象ソースの選択")
    st.info("AIが見つけてきた最新ソースの候補です。深掘りしてほしいものにチェックを入れてください。")
    
    selected_urls = []
    
    for i, res in enumerate(st.session_state.candidates):
        title = res.get('title', 'No Title')
        url = res.get('url', '')
        snippet = res.get('content', '')
        
        st.markdown(f"**{title}**")
        st.caption(f"🔗 {url}")
        st.write(f"概要: {snippet}")
        # デフォルトで上から3つはチェックを入れておく
        if st.checkbox(f"このソースを深掘りする", key=f"chk_{i}", value=(i < 3)):
            selected_urls.append(url)
        st.markdown("---")
        
    if st.button("🚀 選択したソースでディープリサーチ開始"):
        st.session_state.selected_urls = selected_urls
        st.session_state.step = 3
        st.rerun()
        
    if st.button("⬅️ Step 1に戻る"):
        st.session_state.step = 1
        st.rerun()

# ==========================================
# UI ステップ3：深掘り＆レポート生成
# ==========================================
elif st.session_state.step == 3:
    st.title("🧠 Step 3: ディープリサーチ＆レポート生成")
    
    # ユーザー指定URLと選択したURLを合体
    all_target_urls = st.session_state.mandatory_urls + st.session_state.selected_urls
    
    if not all_target_urls:
        st.warning("ソースが一つも選択されていませんが、AIの知識のみで生成します。")
        
    st.write(f"📚 以下の {len(all_target_urls)} 件のURL（およびその階層下のPDF）を精読しています...")
    
    # --- 全ソースの深掘り読み込み ---
    context_data = ""
    progress_bar = st.progress(0)
    for i, url in enumerate(all_target_urls):
        st.text(f"📖 読み込み中: {url}")
        extracted_text = deep_read_url(url)
        context_data += f"\n\n【ソースURL: {url} の内容】\n{extracted_text}\n"
        progress_bar.progress((i + 1) / len(all_target_urls))
        time.sleep(1) # サーバー負荷軽減
        
    st.success("✅ ソースの精読が完了しました。レポートを執筆します。")
    
    # --- AIによるレポート生成 ---
    genai.configure(api_key=gemini_api_key)
    model = genai.GenerativeModel(model_name='gemini-3.1-flash-lite-preview')
    
    prompt = f"""
    対象企業: {st.session_state.company_name}
    
    以下の【収集した最新一次情報】を最も重要なファクトとして読み込み、企業研究レポートを作成してください。
    
    【収集した最新一次情報（Web本文・PDFデータ）】
    {context_data}
    
    【出力要件】
    1. 業界構造とビジネスモデル（収益の仕組みと最新トレンド）
    2. 競合比較・SWOT分析（独自の強みと課題）
    3. 働く社員と求める人物像（採用情報やインタビューに基づく）
    4. キャリアパスと市場価値（3年後、30歳時点など）
    
    事実と推論を明確に分け、見出しをつけて論理的に記述してください。
    """
    
    with st.spinner("AIが収集した膨大なデータを統合し、レポートを執筆中..."):
        try:
            response = model.generate_content(prompt)
            st.markdown(response.text)
            
            # --- Word出力 ---
            doc = Document()
            doc.add_heading(f"{st.session_state.company_name} ディープリサーチレポート", 0)
            doc.add_paragraph(response.text)
            
            bio = BytesIO()
            doc.save(bio)
            st.download_button(
                label="📄 Wordレポートをダウンロード",
                data=bio.getvalue(),
                file_name=f"{st.session_state.company_name}_DeepReport.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
        except Exception as e:
            st.error(f"レポート生成中にエラーが発生しました: {e}")
            
    if st.button("🔄 最初からやり直す"):
        st.session_state.step = 1
        st.session_state.candidates = []
        st.rerun()
