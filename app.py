import streamlit as st
import google.generativeai as genai
import requests
from bs4 import BeautifulSoup
import PyPDF2
from io import BytesIO
from docx import Document
import time
from urllib.parse import urljoin, urlparse
import re

# --- 初期設定 ---
st.set_page_config(page_title="プロフェッショナル企業分析AI", layout="wide")

st.markdown("""
    <style>
    .source-card { background-color: white; padding: 15px; border-radius: 8px; border-left: 5px solid #007bff; margin-bottom: 10px; box-shadow: 1px 1px 3px rgba(0,0,0,0.1); }
    </style>
    """, unsafe_allow_html=True)

st.sidebar.title("🛠️ API設定")
gemini_key = st.sidebar.text_input("Gemini API Key", value=st.secrets.get("GEMINI_API_KEY", ""), type="password")

if "step" not in st.session_state: st.session_state.step = 1
if "search_results" not in st.session_state: st.session_state.search_results = {"IR・財務": [], "PR・ニュース": [], "ヒト・組織": []}

# --- ツール関数：各ポータルから「個別記事・PDF」の直リンクを抽出 ---
def get_ir_links(hp_url):
    """公式HPからIR関連のリンク（特にPDF）を抽出"""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(hp_url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.content, 'html.parser')
        links = []
        for a in soup.find_all('a', href=True):
            url = urljoin(hp_url, a['href'])
            text = a.get_text().strip()
            # ir, pdf, 決算などのキーワードでフィルタ
            if any(k in text.lower() or k in url.lower() for k in ["ir", "investor", "pdf", "決算", "中期経営計画"]):
                if url not in [l['url'] for l in links]:
                    links.append({"title": text or "IR資料", "url": url})
            if len(links) >= 5: break
        return links
    except:
        return []

def get_prtimes_links(pr_url):
    """PR TIMESの企業ページから、個別のプレスリリース記事URLを抽出"""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(pr_url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.content, 'html.parser')
        links = []
        # PR TIMESの個別記事URLのパターン (/main/html/rd/p/...) を探す
        for a in soup.find_all('a', href=re.compile(r'/main/html/rd/p/')):
            url = urljoin("https://prtimes.jp", a['href'])
            title = a.get_text().strip()
            if title and url not in [l['url'] for l in links]:
                links.append({"title": title[:40]+"...", "url": url})
            if len(links) >= 5: break
        return links
    except:
        return []

def get_wantedly_links(rec_url):
    """Wantedlyの企業ページから、個別のストーリー（インタビュー）URLを抽出"""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(rec_url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.content, 'html.parser')
        links = []
        # post_articles や stories を探す
        for a in soup.find_all('a', href=re.compile(r'/(post_articles|stories)/')):
            url = urljoin("https://www.wantedly.com", a['href'])
            title = a.get_text().strip()
            if title and url not in [l['url'] for l in links]:
                links.append({"title": title[:40]+"...", "url": url})
            if len(links) >= 5: break
        return links
    except:
        return []

def deep_read_content(url):
    """Webページの本文、またはPDFの全テキストを抽出"""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        if url.lower().endswith(".pdf"):
            res = requests.get(url, headers=headers, timeout=15)
            reader = PyPDF2.PdfReader(BytesIO(res.content))
            return "\n".join([p.extract_text() for p in reader.pages])[:15000] # 最大1.5万文字
        
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        soup = BeautifulSoup(res.content, 'html.parser')
        for s in soup(['script', 'style', 'nav', 'header', 'footer']): s.decompose()
        return soup.get_text(separator='\n', strip=True)[:10000]
    except Exception as e:
        return f"[読み込み失敗: {e}]"

# --- エージェントのデフォルトプロンプト定義 ---
DEFAULT_PROMPTS = {
    "finance": """あなたは財務・戦略の専門家です。与えられたIR資料や決算PDFから、以下の情報を【具体的な数値や事実】とともに抽出してください。
①誰からどうやってお金を稼いでいるか（ビジネスモデルと収益構造）
②最新の決算資料で経営陣が強調している「今後の注力領域」
③資料から読み取れる、他社には真似できない独自の強み（競合優位性）
※推論はせず、事実と経営陣の意図を徹底的に深く書き出してください。""",

    "pr": """あなたは最新のビジネストレンドを追う記者です。与えられたプレスリリースから最新動向を抽出してください。
①直近1年以内の重要な新サービス、業務提携、イベントなどの具体例を最低3つ挙げる。
②提携先の企業名や、リリースに記載されている具体的な実績（数値）を省略せずに記載する。
※箇条書きを用いて情報量を最大化して出力してください。""",

    "hr": """あなたは人事・カルチャーの専門家です。与えられた社員インタビュー記事から、組織のリアルな実態を抽出してください。
①記事に登場する【実在の社員名】を必ず特定し、その人の前職や入社理由、現在のミッションを記述する。
②記事内のエピソードから、この会社で評価される「マインドセット」を言語化する。
※「多様な人材が〜」のような抽象表現は禁止。必ず個別エピソードを記載してください。""",

    "editor": """あなたは超一流の戦略コンサルタント兼キャリアアドバイザーです。
3人のリサーチャーから上がってきたリサーチ結果を統合し、以下の【5章構成】のレポートを完成させてください。

【出力構成】
1. 業界構造とビジネスモデル
2. 事業分析（収益構造と最新動向）
3. 競合比較・SWOT分析
4. 組織にいる人材と求める人物像
5. キャリアパスと市場価値推論

【厳守事項】
・リサーチャーが挙げた「具体的な数値」「提携先企業名」「実在の社員名とエピソード」は絶対に削らず、すべて組み込むこと。単なる要約は厳禁。
・第5章は、第1〜4章の事実を論理的につなぎ、「この会社で3年働くと、どのようなスキルが身につき、30歳時点で他業界からどう評価されるか」を大胆かつ具体的に推論すること。"""
}

# ==========================================
# STEP 1: 起点URLの入力
# ==========================================
if st.session_state.step == 1:
    st.title("🎯 Step 1: 企業ポータルの指定")
    st.info("各メディアの企業ページURLを入力すると、裏側で自動的に『読むべき個別記事』を探し出します。")
    
    company = st.text_input("企業名", placeholder="例：株式会社マクアケ")
    col1, col2, col3 = st.columns(3)
    with col1: hp_url = st.text_input("公式HP URL (必須)", placeholder="https://www.makuake.co.jp/")
    with col2: pr_url = st.text_input("PR TIMES 企業ページ", placeholder="https://prtimes.jp/main/html/searchrl/company_id/12345")
    with col3: rec_url = st.text_input("Wantedly 企業ページ", placeholder="https://www.wantedly.com/companies/makuake")

    if st.button("🔍 サイト内から最新記事・PDFを抽出"):
        if not gemini_key:
            st.error("APIキーを設定してください")
        elif not company or not hp_url:
            st.error("企業名と公式HPのURLは必須です")
        else:
            with st.spinner("各サイトの構造を解析し、個別記事の直リンクを抽出中..."):
                st.session_state.search_results["IR・財務"] = get_ir_links(hp_url) if hp_url else []
                st.session_state.search_results["PR・ニュース"] = get_prtimes_links(pr_url) if pr_url else []
                st.session_state.search_results["ヒト・組織"] = get_wantedly_links(rec_url) if rec_url else []
                
                st.session_state.company = company
                st.session_state.step = 2
                st.rerun()

# ==========================================
# STEP 2: ソース選択 ＆ プロンプト編集
# ==========================================
elif st.session_state.step == 2:
    st.title(f"⚙️ Step 2: ソース選択とAIへの指示 (対象: {st.session_state.company})")
    
    # --- UI: プロンプトのカスタマイズ ---
    st.subheader("🧠 各エージェントへの指示（プロンプト）の調整")
    with st.expander("指示書を編集する（デフォルトでも強力に動作します）", expanded=False):
        st.session_state.prompt_fin = st.text_area("🕵️‍♂️ 財務・戦略エージェントへ", value=DEFAULT_PROMPTS["finance"], height=150)
        st.session_state.prompt_pr = st.text_area("🕵️‍♂️ 広報エージェントへ", value=DEFAULT_PROMPTS["pr"], height=150)
        st.session_state.prompt_hr = st.text_area("🕵️‍♂️ ヒト・組織エージェントへ", value=DEFAULT_PROMPTS["hr"], height=150)
        st.session_state.prompt_ed = st.text_area("👑 統合エージェント（編集長）へ", value=DEFAULT_PROMPTS["editor"], height=250)

    # --- UI: ソースの選択 ---
    st.subheader("📚 読み込ませる個別記事・PDFの選択")
    st.info("AIが自動抽出したリンクです。チェックが入ったものを『全文』読み込みます。")
    
    selected_urls = {"IR・財務": [], "PR・ニュース": [], "ヒト・組織": []}
    tabs = st.tabs(list(st.session_state.search_results.keys()))

    for i, cat in enumerate(st.session_state.search_results.keys()):
        with tabs[i]:
            if not st.session_state.search_results[cat]:
                st.warning("このカテゴリのリンクは見つかりませんでした。URLが正しいか確認してください。")
            for j, item in enumerate(st.session_state.search_results[cat]):
                st.markdown(f"<div class='source-card'><b>{item['title']}</b><br><small>{item['url']}</small></div>", unsafe_allow_html=True)
                if st.checkbox("このページを精読する", key=f"chk_{cat}_{j}", value=True):
                    selected_urls[cat].append(item['url'])

    if st.button("🚀 マルチ・エージェントによるディープリサーチ開始"):
        st.session_state.selected_urls = selected_urls
        st.session_state.step = 3
        st.rerun()
        
    if st.button("⬅️ 戻る"):
        st.session_state.step = 1
        st.rerun()

# ==========================================
# STEP 3: マルチエージェント並列処理とレポート統合
# ==========================================
elif st.session_state.step == 3:
    st.title("📊 Step 3: レポート生成")
    genai.configure(api_key=gemini_key)
    model = genai.GenerativeModel('gemini-3.1-flash-lite-preview')
    
    agent_reports = {}
    
    # 1. 各リサーチャーエージェントの実行
    categories = [
        ("IR・財務", "prompt_fin", "財務・戦略"),
        ("PR・ニュース", "prompt_pr", "広報・ニュース"),
        ("ヒト・組織", "prompt_hr", "ヒト・組織")
    ]
    
    for cat_name, prompt_key, agent_name in categories:
        urls = st.session_state.selected_urls.get(cat_name, [])
        if not urls:
            agent_reports[cat_name] = f"【{cat_name}】に関する情報ソースはありませんでした。"
            continue
            
        with st.status(f"🕵️‍♂️ {agent_name}エージェントがデータを精読中...", expanded=True) as status:
            context = ""
            for url in urls:
                st.write(f"📖 読み込み中: {url}")
                context += f"\n--- {url} ---\n{deep_read_content(url)}\n"
            
            st.write("🧠 抽出と分析を実行中...")
            prompt = f"対象企業: {st.session_state.company}\n\n【一次情報】\n{context}\n\n【あなたの任務】\n{st.session_state.get(prompt_key)}"
            
            try:
                # API制限回避のためのインターバル
                time.sleep(3)
                resp = model.generate_content(prompt)
                agent_reports[cat_name] = resp.text
                status.update(label=f"✅ {agent_name}エージェントの分析完了！", state="complete")
            except Exception as e:
                agent_reports[cat_name] = f"分析エラー: {e}"
                status.update(label=f"⚠️ {agent_name}エージェント エラー", state="error")

    # 2. 統合エージェント（編集長）の実行
    with st.spinner("👑 統合エージェントがすべての素材を結合し、最終レポートを執筆中..."):
        integration_context = f"""
        【財務・戦略エージェントの報告】
        {agent_reports.get("IR・財務", "")}
        
        【広報エージェントの報告】
        {agent_reports.get("PR・ニュース", "")}
        
        【ヒト・組織エージェントの報告】
        {agent_reports.get("ヒト・組織", "")}
        """
        
        final_prompt = f"対象企業: {st.session_state.company}\n\n【リサーチャーからの報告素材】\n{integration_context}\n\n【あなたの任務】\n{st.session_state.get('prompt_ed')}"
        
        try:
            time.sleep(3)
            final_response = model.generate_content(final_prompt)
            final_text = final_response.text
            st.success("🎉 全プロセスが完了しました！")
            
            # 結果の表示とダウンロード
            st.markdown(final_text)
            
            doc = Document()
            doc.add_heading(f"{st.session_state.company} 企業研究レポート", 0)
            doc.add_paragraph(final_text)
            bio = BytesIO(); doc.save(bio)
            st.download_button("📄 レポートをWordでダウンロード", data=bio.getvalue(), file_name=f"{st.session_state.company}_Report.docx")
            
        except Exception as e:
            st.error(f"最終統合中にエラーが発生しました: {e}")

    if st.button("🔄 最初からやり直す"):
        st.session_state.step = 1
        st.rerun()
