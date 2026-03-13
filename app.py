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

if "search_done" not in st.session_state: st.session_state.search_done = False
if "research_done" not in st.session_state: st.session_state.research_done = False
if "search_results" not in st.session_state: st.session_state.search_results = {}

# ==========================================
# 1. ツール関数（情報抽出とディープリード）
# ==========================================
def extract_text_from_url(url):
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

# ==========================================
# 2. プロンプト定義（考察力とストーリー統合の強化）
# ==========================================
PROMPT_FIN = (
    "あなたは超一流の財務・戦略リサーチャーです。以下の資料からファクト（事実）を抽出するだけでなく、プロの視点で「考察」を加えてください。\n"
    "【必須項目】\n"
    "1. 決算数値と収益モデルの仕組み（事実）\n"
    "2. 経営陣が言及している注力施策と、現在の「経営課題（成長の壁）」（事実＋考察）\n"
    "3. 独自の強みと、それを支える戦略的意図（事実＋考察）\n"
    "※資料の事実をエビデンスとしつつ、あなたの高度なビジネス知見を交えて深く分析してください。"
)

PROMPT_PR = (
    "あなたは敏腕のビジネス記者です。以下の記事から事実を抽出し、その背景にある「企業の狙い」を考察してください。\n"
    "【必須項目】\n"
    "1. 新サービスや業務提携の具体名と、提携先企業名（事実）\n"
    "2. リリースに記載されている具体的な実績数値（事実）\n"
    "3. なぜ今この動きをしたのか、業界動向を踏まえた戦略的意図（考察）\n"
    "※要約せず、具体名を網羅し、企業の進化の方向性を探ってください。"
)

PROMPT_HR = (
    "あなたは組織開発のプロフェッショナルです。以下のインタビュー記事から、組織のリアルな生態系を抽出・考察してください。\n"
    "【必須項目】\n"
    "1. 実在の社員名、役職、前職、入社理由（事実）\n"
    "2. 現在の具体的なミッションと、それが会社の「経営課題」の解決にどう繋がっているか（事実＋考察）\n"
    "3. 現場で本当に評価されているマインドセット（考察）\n"
    "※抽象表現は排除し、個別エピソードを経営視点で解説してください。"
)

# --- 編集長（統合）用 セクション別プロンプト ---
# 一括書きによる「内容の薄まり」を防ぐため、1章ずつ個別に指示を出します
EDITOR_PROMPTS = {
    "1. 業界構造とビジネスモデル": (
        "提供された全ファクトを用いて、『1. 業界構造とビジネスモデル』の章を1000文字以上で執筆してください。\n"
        "読者が『この会社がどのようなエコシステムで稼いでいるのか』を構造的に理解できるよう、AIのビジネス知見で補完しながら重厚に解説してください。具体的な数値や強みを含めること。"
    ),
    "2. 事業分析（収益構造と最新動向）": (
        "提供された全ファクトを用いて、『2. 事業分析（収益構造と最新動向）』の章を1000文字以上で執筆してください。\n"
        "過去からの成り立ち、現在仕込んでいるPRや提携（最新動向）、そして未来（中期経営計画）への流れという「時間軸（進化論）」を意識して、一つの物語として記述してください。"
    ),
    "3. 競合比較・SWOT分析": (
        "提供された全ファクトを用いて、『3. 競合比較・SWOT分析』の章を1000文字以上で執筆してください。\n"
        "この会社が現在直面している「最大の経営課題（ボトルネック）」を中心に据え、それを乗り越えるための強み（S）と弱み（W）を、あなたの高度な推論を交えて深く分析してください。"
    ),
    "4. 組織にいる人材と求める人物像": (
        "提供された全ファクトを用いて、『4. 組織にいる人材と求める人物像』の章を1000文字以上で執筆してください。\n"
        "リサーチャーが挙げた「実在の社員名と個別エピソード」を必ずすべて本文に組み込み、彼らが経営課題をどう解決しているかを描写してください。"
    ),
    "5. キャリアパスと市場価値推論": (
        "提供された全ファクトを用いて、『5. キャリアパスと市場価値推論』の章を1000文字以上で執筆してください。\n"
        "これまでの第1〜4章のロジックを統合し、「この会社で3年働くと、どのような独自スキルが身につき、30歳時点で転職市場においてどの業界から、どの程度の想定年収でスカウトされるか」を、エビデンス（事実）に基づいて大胆かつ具体的に推論してください。"
    )
}

# ==========================================
# UIセクション 1: 入力と広域・精密検索
# ==========================================
st.title("🎯 真・高度企業分析: マルチエージェント・ディープリサーチ")
st.write("企業情報に基づき、AIが『情報の抽出 ➡ 考察 ➡ ストーリー統合』を自動で行います。")

col1, col2 = st.columns(2)
with col1:
    company = st.text_input("企業名", value="株式会社マクアケ")
    hp_url = st.text_input("公式HP URL", value="https://www.makuake.co.jp/")
with col2:
    pr_url = st.text_input("PR TIMES URL", value="https://prtimes.jp/main/html/searchrlp/company_id/36381")
    rec_url = st.text_input("Wantedly URL", value="https://www.wantedly.com/companies/makuake")

if st.button("🔍 1. 広域メディアから最新・重要記事を抽出", type="primary"):
    if not tavily_key: st.error("サイドバーにTavily APIキーを設定してください。"); st.stop()
    
    with st.spinner("Tavily AIを用いて『IR三種の神器』と『マルチドメイン記事』を抽出中..."):
        client = TavilyClient(api_key=tavily_key)
        results = {"IR・財務": [], "PR・ニュース": [], "ヒト・組織": []}
        
        current_year = datetime.date.today().year
        recent_years = f"{current_year-1} OR {current_year}"
        
        try:
            # 1. IR: 三種の神器と最新年にピンポイント指定
            if hp_url:
                domain = urlparse(hp_url).netloc
                q_ir = f"{company} (決算短信 OR 決算説明会資料 OR 中期経営計画) {recent_years} site:{domain}"
                raw_ir = client.search(query=q_ir, max_results=10).get("results", [])
                results["IR・財務"] = raw_ir[:5] # 重要な5件に絞る
            
            # 2. PR: ID指定(自社) ＋ 外部メディア(日経/note等)のintitle検索
            pr_id_match = re.search(r'company_id/(\d+)', pr_url) if pr_url else None
            pr_id = pr_id_match.group(1) if pr_id_match else ""
            
            q_pr_ext = f"intitle:{company} (提携 OR リリース OR 新機能) site:nikkei.com OR site:note.com OR site:prtimes.jp"
            raw_pr = client.search(query=q_pr_ext, max_results=20).get("results", [])
            
            filtered_pr = []
            for r in raw_pr:
                # PR TIMESの場合は自社IDのみ、他メディアはそのまま追加
                if "prtimes.jp" in r["url"]:
                    if pr_id and pr_id in r["url"] and "/rd/p/" in r["url"]:
                        filtered_pr.append(r)
                else:
                    filtered_pr.append(r)
            results["PR・ニュース"] = filtered_pr[:10] # 10件に増量
            
            # 3. HR: Wantedly ＋ 外部メディア(note)のハイブリッド
            rec_slug_match = re.search(r'companies/([^/]+)', rec_url) if rec_url else None
            rec_slug = rec_slug_match.group(1) if rec_slug_match else company
            
            q_hr_ext = f"intitle:{company} (インタビュー OR 採用 OR 社員) site:wantedly.com OR site:note.com"
            raw_hr = client.search(query=q_hr_ext, max_results=20).get("results", [])
            
            filtered_hr = []
            for r in raw_hr:
                if "wantedly.com" in r["url"]:
                    if rec_slug in r["url"] or "post_articles" in r["url"]: filtered_hr.append(r)
                else:
                    filtered_hr.append(r)
            results["ヒト・組織"] = filtered_hr[:10] # 10件に増量

            st.session_state.search_results = results
            st.session_state.search_done = True
            st.session_state.research_done = False
            st.rerun()
            
        except Exception as e:
            st.error(f"検索エラー: {e}")

st.markdown("---")

# ==========================================
# UIセクション 2: ソース選択
# ==========================================
if st.session_state.search_done:
    st.subheader("📚 2. 精読対象の選択（情報量の担保）")
    st.info("広域検索により外部メディアも含めて抽出しました。チェックを入れた記事を全てディープリードします。")
    
    selected_urls = {"IR・財務": [], "PR・ニュース": [], "ヒト・組織": []}
    tabs = st.tabs(list(st.session_state.search_results.keys()))

    for i, cat in enumerate(st.session_state.search_results.keys()):
        with tabs[i]:
            if not st.session_state.search_results[cat]:
                st.warning("対象記事が見つかりませんでした。")
            for j, item in enumerate(st.session_state.search_results[cat]):
                st.markdown(f"<div class='source-card'><b>{item['title']}</b><br><a href='{item['url']}' target='_blank'><small>{item['url']}</small></a></div>", unsafe_allow_html=True)
                if st.checkbox("精読する", key=f"chk_{cat}_{j}", value=True):
                    selected_urls[cat].append(item['url'])

    if st.button("🚀 3. 戦略的ファクト抽出とセクション別レポート執筆を開始", type="primary"):
        if not gemini_key: st.error("サイドバーにGemini APIキーを設定してください。"); st.stop()
        st.session_state.selected_urls = selected_urls
        st.session_state.research_done = True
        st.rerun()

    st.markdown("---")

# ==========================================
# UIセクション 3: エージェント実行と統合レポート（セクション別生成）
# ==========================================
if st.session_state.research_done:
    st.subheader("🧠 3. ディープリサーチ進行状況")
    
    genai.configure(api_key=gemini_key)
    model = genai.GenerativeModel('gemini-3.1-flash-lite-preview')
    
    categories = [
        ("IR・財務", PROMPT_FIN, "財務・戦略"),
        ("PR・ニュース", PROMPT_PR, "広報・戦略"),
        ("ヒト・組織", PROMPT_HR, "人事・組織開発")
    ]
    
    fact_logs_all = {}

    # --- フェーズ1: 考察付きファクト抽出 ---
    for cat_name, prompt_text, agent_name in categories:
        urls = st.session_state.selected_urls.get(cat_name, [])
        if not urls:
            fact_logs_all[cat_name] = "情報なし"
            continue
            
        with st.status(f"🕵️‍♂️ {agent_name}担当が事実の抽出と戦略的考察を実行中...", expanded=True) as status:
            cat_facts = ""
            for url in urls:
                st.write(f"📄 分析中: {url}")
                raw_text = extract_text_from_url(url)
                
                fact_prompt = f"対象企業: {company}\nソースURL: {url}\n\n【一次情報】\n{raw_text}\n\n【あなたの任務】\n{prompt_text}"
                try:
                    time.sleep(2) # API制限回避
                    resp = model.generate_content(fact_prompt)
                    cat_facts += f"\n◆ソース: {url}\n{resp.text}\n"
                    st.markdown(f"<div class='fact-log'><b>✅ 抽出・考察完了</b><br>{resp.text[:100]}...</div>", unsafe_allow_html=True)
                except Exception as e:
                    st.write(f"⚠️ 分析エラー: {e}")
            
            fact_logs_all[cat_name] = cat_facts
            status.update(label=f"🎯 {agent_name}担当の分析完了！", state="complete")

    # --- フェーズ2: 編集長によるセクション別・超長文生成 ---
    st.subheader("📊 最終統合レポート（物語と推論の構築）")
    
    integration_context = f"""
    【リサーチャーが収集した事実と考察一覧】
    ■ 財務・戦略ファクト\n{fact_logs_all.get("IR・財務", "")}
    ■ 広報・ニュースファクト\n{fact_logs_all.get("PR・ニュース", "")}
    ■ ヒト・組織ファクト\n{fact_logs_all.get("ヒト・組織", "")}
    """
    
    final_report_text = ""
    
    with st.status("👑 編集長が経営課題を軸にストーリーを編纂し、1章ずつ書き上げています...", expanded=True) as ed_status:
        for section_title, section_prompt in EDITOR_PROMPTS.items():
            st.write(f"✍️ {section_title} を執筆中...")
            
            prompt_ed = f"対象企業: {company}\n\n{integration_context}\n\n【あなたの任務】\n{section_prompt}"
            
            try:
                time.sleep(3) # セクション間のAPI制限回避
                sec_resp = model.generate_content(prompt_ed)
                final_report_text += f"## {section_title}\n\n{sec_resp.text}\n\n---\n\n"
            except Exception as e:
                st.error(f"{section_title}の執筆中にエラー: {e}")
                
        ed_status.update(label="🎉 圧倒的な厚みを持つ最終レポートが完成しました！", state="complete")

    # 結果の表示とダウンロード
    st.markdown(final_report_text)
    
    doc = Document()
    doc.add_heading(f"{company} 企業研究・キャリア推論レポート", 0)
    for para in final_report_text.split('\n'):
        if para.startswith('## '):
            doc.add_heading(para.replace('## ', ''), level=1)
        elif para.strip() and para != "---":
            doc.add_paragraph(para)
            
    bio = BytesIO(); doc.save(bio)
    st.download_button("📄 レポートをWordでダウンロード", data=bio.getvalue(), file_name=f"{company}_DeepReport.docx", type="primary")

    if st.button("🔄 最初からやり直す"):
        for key in ["search_done", "research_done", "search_results"]:
            st.session_state[key] = False if isinstance(st.session_state[key], bool) else {}
        st.rerun()
