import streamlit as st
import google.generativeai as genai
import requests
from bs4 import BeautifulSoup
import PyPDF2
from io import BytesIO
from docx import Document
from tavily import TavilyClient
import time
from urllib.parse import urlparse
import re
import datetime

# ==========================================
# 0. 初期設定とUIスタイル
# ==========================================
st.set_page_config(page_title="プロフェッショナル企業分析AI", layout="wide")
st.markdown("""
    <style>
    .source-card { background-color: white; padding: 15px; border-radius: 8px; border-left: 5px solid #007bff; margin-bottom: 10px; box-shadow: 1px 1px 3px rgba(0,0,0,0.1); }
    .fact-log { background-color: #f8f9fa; border-left: 4px solid #28a745; padding: 10px; margin: 10px 0; font-size: 0.9em; }
    </style>
    """, unsafe_allow_html=True)

st.sidebar.title("🛠️ API設定")
gemini_key = st.sidebar.text_input("Gemini API Key", value=st.secrets.get("GEMINI_API_KEY", ""), type="password")
tavily_key = st.sidebar.text_input("Tavily API Key", value=st.secrets.get("TAVILY_API_KEY", ""), type="password")

# --- セッションステートの初期化 ---
if "search_done" not in st.session_state: st.session_state.search_done = False
if "research_done" not in st.session_state: st.session_state.research_done = False
if "search_results" not in st.session_state: st.session_state.search_results = {}

# ==========================================
# 1. ツール関数（情報抽出とディープリード）
# ==========================================
def extract_text_from_url(url):
    """URLからテキストを抽出（PDF/HTML両対応）"""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        if url.lower().endswith(".pdf"):
            res = requests.get(url, headers=headers, timeout=15)
            reader = PyPDF2.PdfReader(BytesIO(res.content))
            return "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])[:20000]
        
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        soup = BeautifulSoup(res.content, 'html.parser')
        for s in soup(['script', 'style', 'nav', 'header', 'footer']): s.decompose()
        return soup.get_text(separator='\n', strip=True)[:10000]
    except Exception as e:
        return f"[抽出スキップ: {e}]"

# --- デフォルトプロンプト（エラー防止のため安全な書き方に修正） ---
PROMPT_FIN = (
    "あなたは財務・戦略リサーチャーです。以下の資料からファクト（事実）を箇条書きで抽出してください。\n"
    "【必須抽出項目】①具体的な売上・利益の数値 ②収益モデルの仕組み ③経営陣が言及している注力施策 ④独自の強み\n"
    "※推論は不要です。資料にある固有名詞や数値を絶対に漏らさずリスト化してください。"
)

PROMPT_PR = (
    "あなたは広報・ニュースリサーチャーです。以下の記事からファクト（事実）を箇条書きで抽出してください。\n"
    "【必須抽出項目】①新サービス・業務提携の具体名 ②提携先企業名 ③リリースに記載されている具体的な実績（〇〇万ユーザー等）\n"
    "※要約せず、具体的な名称をすべてリストアップしてください。"
)

PROMPT_HR = (
    "あなたは人事リサーチャーです。以下のインタビュー記事からファクト（事実）を箇条書きで抽出してください。\n"
    "【必須抽出項目】①記事に登場する実在の社員名と役職 ②その人の前職や入社理由 ③現在の具体的なミッション ④評価されているマインドセット\n"
    "※「多様な人材が活躍」といった抽象表現は排除し、必ず個別名とエピソードを抽出してください。"
)

PROMPT_ED = (
    "あなたは超一流の戦略コンサルタント兼キャリアアドバイザーです。\n"
    "3人のリサーチャーが抽出した【ファクト・ログ（事実のリスト）】を統合し、以下の【5章構成】で重厚なレポートを執筆してください。\n\n"
    "【出力構成】\n"
    "1. 業界構造とビジネスモデル\n"
    "2. 事業分析（収益構造と最新動向）\n"
    "3. 競合比較・SWOT分析\n"
    "4. 組織にいる人材と求める人物像\n"
    "5. キャリアパスと市場価値推論\n\n"
    "【厳守事項】\n"
    "・リサーチャーが報告した「数値」「提携先企業名」「実在の社員名とエピソード」はすべて本文に組み込むこと。\n"
    "・第5章は、第1〜4章の事実を論理的につなぎ、「この会社で3年働くと30歳時点で他業界からどう評価されるか」を大胆かつ具体的に推論すること。"
)

# ==========================================
# UIセクション 1: 入力とプロンプト編集
# ==========================================
st.title("🎯 高度企業分析: マルチエージェント・リサーチ")
st.write("企業情報とプロンプトを入力し、段階的にリサーチを進めます。")

col1, col2 = st.columns(2)
with col1:
    company = st.text_input("企業名", value="株式会社マクアケ")
    hp_url = st.text_input("公式HP URL", value="https://www.makuake.co.jp/")
with col2:
    pr_url = st.text_input("PR TIMES URL", value="https://prtimes.jp/main/html/searchrlp/company_id/36381")
    rec_url = st.text_input("Wantedly URL", value="https://www.wantedly.com/companies/makuake")

with st.expander("⚙️ 各エージェントへの指示（プロンプト）を編集する", expanded=False):
    prompt_fin = st.text_area("🕵️‍♂️ 財務・戦略担当へ", value=PROMPT_FIN, height=120)
    prompt_pr = st.text_area("🕵️‍♂️ 広報担当へ", value=PROMPT_PR, height=120)
    prompt_hr = st.text_area("🕵️‍♂️ ヒト・組織担当へ", value=PROMPT_HR, height=120)
    prompt_ed = st.text_area("👑 統合エージェント（編集長）へ", value=PROMPT_ED, height=200)

if st.button("🔍 1. 対象メディアから最新の個別記事をリストアップ", type="primary"):
    if not tavily_key: st.error("サイドバーにTavily APIキーを設定してください。"); st.stop()
    
    with st.spinner("Tavily AIとPythonフィルタリングを用いて最新記事を抽出中..."):
        client = TavilyClient(api_key=tavily_key)
        results = {"IR・財務": [], "PR・ニュース": [], "ヒト・組織": []}
        
        # 直近の年数を取得（例：2025 OR 2026）
        current_year = datetime.date.today().year
        recent_years = f"{current_year-1} OR {current_year}"
        
        try:
            # 1. IR情報の検索 (直近2年に絞る)
            if hp_url:
                domain = urlparse(hp_url).netloc
                q_ir = f"{company} (決算説明資料 OR 中期経営計画 OR 統合報告書) {recent_years} site:{domain}"
                raw_ir = client.search(query=q_ir, max_results=10).get("results", [])
                results["IR・財務"] = raw_ir[:5]
            
            # 2. PR TIMESの検索 (広く検索し、Pythonで厳格に絞る)
            if pr_url:
                pr_id_match = re.search(r'company_id/(\d+)', pr_url)
                pr_id = pr_id_match.group(1) if pr_id_match else ""
                
                q_pr = f"{company} site:prtimes.jp"
                raw_pr = client.search(query=q_pr, max_results=20).get("results", [])
                
                filtered_pr = []
                for r in raw_pr:
                    if "/main/html/rd/p/" in r["url"]:
                        if pr_id:
                            if pr_id in r["url"]: filtered_pr.append(r)
                        else:
                            filtered_pr.append(r)
                results["PR・ニュース"] = filtered_pr[:5]
                
            # 3. Wantedlyの検索 (広く検索し、Pythonで厳格に絞る)
            if rec_url:
                rec_slug_match = re.search(r'companies/([^/]+)', rec_url)
                rec_slug = rec_slug_match.group(1) if rec_slug_match else ""
                
                q_hr = f"{company} インタビュー site:wantedly.com"
                raw_hr = client.search(query=q_hr, max_results=20).get("results", [])
                
                filtered_hr = []
                for r in raw_hr:
                    if rec_slug:
                        if rec_slug in r["url"]: filtered_hr.append(r)
                    else:
                        if "post_articles" in r["url"] or "stories" in r["url"]:
                            filtered_hr.append(r)
                results["ヒト・組織"] = filtered_hr[:5]

            st.session_state.search_results = results
            st.session_state.search_done = True
            st.session_state.research_done = False
            st.rerun()
            
        except Exception as e:
            st.error(f"検索エラーが発生しました: {e}")

st.markdown("---")

# ==========================================
# UIセクション 2: ソース選択
# ==========================================
if st.session_state.search_done:
    st.subheader("📚 2. 精読対象の選択")
    st.info("AIが特定した最新の個別記事です。不要なものはチェックを外してください。")
    
    selected_urls = {"IR・財務": [], "PR・ニュース": [], "ヒト・組織": []}
    tabs = st.tabs(list(st.session_state.search_results.keys()))

    for i, cat in enumerate(st.session_state.search_results.keys()):
        with tabs[i]:
            if not st.session_state.search_results[cat]:
                st.warning("対象記事が見つかりませんでした。")
            for j, item in enumerate(st.session_state.search_results[cat]):
                st.markdown(f"<div class='source-card'><b>{item['title']}</b><br><a href='{item['url']}' target='_blank'><small>{item['url']}</small></a></div>", unsafe_allow_html=True)
                if st.checkbox("このページを精読する", key=f"chk_{cat}_{j}", value=True):
                    selected_urls[cat].append(item['url'])

    if st.button("🚀 3. ファクト抽出とレポート執筆を開始", type="primary"):
        if not gemini_key: st.error("サイドバーにGemini APIキーを設定してください。"); st.stop()
        st.session_state.selected_urls = selected_urls
        st.session_state.research_done = True
        st.rerun()
        
    st.markdown("---")

# ==========================================
# UIセクション 3: エージェント実行とレポート表示
# ==========================================
if st.session_state.research_done:
    st.subheader("🧠 3. ディープリサーチ進行状況")
    
    genai.configure(api_key=gemini_key)
    model = genai.GenerativeModel('gemini-3.1-flash-lite-preview')
    
    categories = [
        ("IR・財務", prompt_fin, "財務・戦略"),
        ("PR・ニュース", prompt_pr, "広報・ニュース"),
        ("ヒト・組織", prompt_hr, "ヒト・組織")
    ]
    
    fact_logs_all = {}

    # --- 1. ファクト抽出フェーズ ---
    for cat_name, prompt_text, agent_name in categories:
        urls = st.session_state.selected_urls.get(cat_name, [])
        if not urls:
            fact_logs_all[cat_name] = "情報なし"
            continue
            
        with st.status(f"🕵️‍♂️ {agent_name}担当がファクトを抽出中...", expanded=True) as status:
            cat_facts = ""
            for url in urls:
                st.write(f"📄 読み込み: {url}")
                raw_text = extract_text_from_url(url)
                
                fact_prompt = f"対象企業: {company}\nソースURL: {url}\n\n【一次情報】\n{raw_text}\n\n【あなたの任務】\n{prompt_text}"
                try:
                    time.sleep(2)
                    resp = model.generate_content(fact_prompt)
                    cat_facts += f"\n◆ソース: {url}\n{resp.text}\n"
                    st.markdown(f"<div class='fact-log'><b>✅ 抽出完了</b><br>{resp.text[:100]}...</div>", unsafe_allow_html=True)
                except Exception as e:
                    st.write(f"⚠️ 抽出エラー: {e}")
            
            fact_logs_all[cat_name] = cat_facts
            status.update(label=f"🎯 {agent_name}担当の抽出完了！", state="complete")

    # --- 2. 最終レポート統合フェーズ ---
    st.subheader("📊 最終統合レポート")
    with st.spinner("👑 統合エージェント（編集長）がファクトを編纂し、キャリア推論を行っています..."):
        
        integration_context = f"""
        【財務・戦略ファクト】\n{fact_logs_all.get("IR・財務", "")}
        【広報・ニュースファクト】\n{fact_logs_all.get("PR・ニュース", "")}
        【ヒト・組織ファクト】\n{fact_logs_all.get("ヒト・組織", "")}
        """
        
        final_prompt = f"対象企業: {company}\n\n【リサーチャーが収集したファクト一覧】\n{integration_context}\n\n【あなたの任務】\n{prompt_ed}"
        
        try:
            time.sleep(2)
            final_response = model.generate_content(final_prompt)
            final_text = final_response.text
            
            st.success("🎉 全プロセスが完了し、レポートが完成しました！")
            st.markdown(final_text)
            
            doc = Document()
            doc.add_heading(f"{company} 企業研究レポート", 0)
            doc.add_paragraph(final_text)
            bio = BytesIO(); doc.save(bio)
            st.download_button("📄 レポートをWordでダウンロード", data=bio.getvalue(), file_name=f"{company}_DeepReport.docx", type="primary")
            
        except Exception as e:
            st.error(f"最終統合中にエラーが発生しました: {e}")
