import streamlit as st
import google.generativeai as genai
import requests
from bs4 import BeautifulSoup
import PyPDF2
from io import BytesIO
from docx import Document
from tavily import TavilyClient
import time
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
            res.raise_for_status()
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
    "※未上場企業などで決算数値がない場合は、事業ビジョンや社長のメッセージから企業の戦略を読み解いてください。\n"
    "【必須項目】\n"
    "1. 決算数値と収益モデルの仕組み（数値がない場合はビジネスモデルの構造）（事実）\n"
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

EDITOR_PROMPTS = {
    "1. 業界構造とビジネスモデル": (
        "提供された全ファクトを用いて、『1. 業界構造とビジネスモデル』の章を1000文字以上で執筆してください。\n"
        "読者が『この会社がどのようなエコシステムで稼いでいるのか』を構造的に理解できるよう、AIのビジネス知見で補完しながら重厚に解説してください。具体的な数値や強みを含めること。"
    ),
    "2. 事業分析（収益構造と最新動向）": (
        "提供された全ファクトを用いて、『2. 事業分析（収益構造と最新動向）』の章を1000文字以上で執筆してください。\n"
        "過去からの成り立ち、現在仕込んでいるPRや提携（最新動向）、そして未来への流れという「時間軸（進化論）」を意識して、一つの物語として記述してください。"
    ),
    "3. 競合比較・SWOT分析": (
        "提供された全ファクトを用いて、『3. 競合比較・SWOT分析』の章を1000文字以上で執筆してください。\n"
        "この会社が現在直面している「最大の経営課題（ボトルネック）」を中心に据え、それを乗り越えるための強み（S）と弱み（W）を深く分析してください。"
    ),
    "4. 組織にいる人材と求める人物像": (
        "提供された全ファクトを用いて、『4. 組織にいる人材と求める人物像』の章を1000文字以上で執筆してください。\n"
        "リサーチャーが挙げた「実在の社員名と個別エピソード」を必ずすべて本文に組み込み、彼らが経営課題をどう解決しているかを描写してください。"
    ),
    "5. キャリアパスと市場価値推論": (
        "提供された全ファクトを用いて、『5. キャリアパスと市場価値推論』の章を1000文字以上で執筆してください。\n"
        "これまでの第1〜4章のロジックを統合し、「この会社で3年働くと、どのような独自スキルが身につき、30歳時点で転職市場においてどの業界から、どの程度の想定年収でスカウトされるか」をエビデンスに基づいて推論してください。"
    )
}

# ==========================================
# UIセクション 1: 入力とハイブリッド検索
# ==========================================
st.title("🎯 真・高度企業分析: マルチエージェント・ディープリサーチ")
st.write("確実な戦略情報と、網羅的に収集した最新ニュース・社員記事を統合し、圧倒的な熱量のレポートを生成します。")

company = st.text_input("🏢 企業名", value="株式会社マクアケ")

# --- 対策3: 未上場対応（最重要ファクトの指定） ---
st.subheader("📊 1-A. 【確実性担保】最重要ファクトの直接指定（IR・ビジョン等）")
ir_urls_input = st.text_area(
    "上場企業の場合は「最新の決算説明会資料」等のPDFリンクを、未上場企業の場合は「コーポレートサイトのVision/Mission」や「社長インタビュー記事」のURLを改行で入力してください。",
    value="https://pdf.irpocket.com/C4477/yD3U/v5c7/O11m.pdf\n", # サンプル
    height=100
)

st.subheader("🌐 1-B. 【網羅的抽出】メディア・採用ページの指定")
col1, col2 = st.columns(2)
with col1:
    pr_url = st.text_input("PR TIMES URL", value="https://prtimes.jp/main/html/searchrlp/company_id/36381")
with col2:
    rec_url = st.text_input("Wantedly URL", value="https://www.wantedly.com/companies/makuake")

with st.expander("⚙️ 各エージェントへの指示（プロンプト）を確認・編集", expanded=False):
    prompt_fin = st.text_area("🕵️‍♂️ 財務・戦略担当へ", value=PROMPT_FIN, height=120)
    prompt_pr = st.text_area("🕵️‍♂️ 広報担当へ", value=PROMPT_PR, height=120)
    prompt_hr = st.text_area("🕵️‍♂️ ヒト・組織担当へ", value=PROMPT_HR, height=120)

if st.button("🔍 1. 対象メディアから最新・重要記事を抽出", type="primary"):
    if not tavily_key: st.error("サイドバーにTavily APIキーを設定してください。"); st.stop()
    
    with st.spinner("Tavily AIの出力を最大化し、数十件の対象記事を抽出・フィルタリング中..."):
        client = TavilyClient(api_key=tavily_key)
        results = {"IR・財務": [], "PR・ニュース": [], "ヒト・組織": []}
        
        # 社名から「株式会社」などを省いた略称を作成（検索ヒット率を劇的に上げるため）
        short_company = company.replace("株式会社", "").replace("合同会社", "").strip()
        
        try:
            # 1. 財務・戦略 (手動入力URL)
            ir_urls = [u.strip() for u in ir_urls_input.split('\n') if u.strip()]
            for i, url in enumerate(ir_urls):
                results["IR・財務"].append({"title": f"指定された重要資料 ({i+1})", "url": url})
            
            # 2. PR・ニュース (Newsモード & 過去1年)
            pr_id_match = re.search(r'company_id/(\d+)', pr_url) if pr_url else None
            pr_id = pr_id_match.group(1) if pr_id_match else short_company
            
            q_pr_ext = f"{short_company} 提携 OR リリース OR 新機能"
            raw_pr = client.search(
                query=q_pr_ext, 
                topic="news", 
                days=365, 
                include_domains=["prtimes.jp"],
                max_results=30
            ).get("results", [])
            
            filtered_pr = []
            for r in raw_pr:
                if pr_id in r["url"] and "/rd/p/" in r["url"]:
                    filtered_pr.append(r)
            results["PR・ニュース"] = filtered_pr[:15]
            
            # 3. ヒト・組織 (圧倒的ボリューム化 & Python側での高純度フィルタ)
            rec_slug_match = re.search(r'companies/([^/]+)', rec_url) if rec_url else None
            rec_slug = rec_slug_match.group(1) if rec_slug_match else short_company
            
            # クエリは極力シンプルにし、ドメインはAPIパラメータで指定
            q_hr_ext = f"{short_company} インタビュー OR 社員 OR 採用 OR カルチャー"
            hr_domains = ["wantedly.com", "note.com", "talentbook.jp", "prtimes.jp", "fastgrow.jp"]
            
            raw_hr = client.search(
                query=q_hr_ext, 
                include_domains=hr_domains, 
                max_results=50
            ).get("results", [])
            
            filtered_hr = []
            bad_words = ["株価", "投資", "業績", "決算", "予想", "分析"] # 除外ワード
            
            for r in raw_hr:
                url_lower = r["url"].lower()
                title_content = (r.get("title", "") + r.get("content", "")).lower()
                
                # ① ノイズキャンセリング（Python側で処理）
                if any(bw in title_content for bw in bad_words):
                    continue
                
                # ② タイトルまたは内容に社名（略称）が含まれているかチェック
                if short_company.lower() not in title_content:
                    continue
                
                # ③ ドメインごとの厳密なURLチェック
                if "wantedly.com" in url_lower:
                    if rec_slug.lower() in url_lower and ("post_articles" in url_lower or "stories" in url_lower):
                        filtered_hr.append(r)
                elif "prtimes.jp" in url_lower:
                    if "/story/" in url_lower: # PR TIMES STORYのみ
                        filtered_hr.append(r)
                else:
                    filtered_hr.append(r)
                    
            results["ヒト・組織"] = filtered_hr[:30] # 30件まで表示

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
    st.subheader("📚 2. 精読対象の確認")
    st.info("数十件の候補からノイズを排除しました。チェックを入れた記事を全てディープリードします。")
    
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
# UIセクション 3: エージェント実行と統合レポート
# ==========================================
if st.session_state.research_done:
    st.subheader("🧠 3. ディープリサーチ進行状況")
    
    genai.configure(api_key=gemini_key)
    model = genai.GenerativeModel('gemini-3.1-flash-lite-preview')
    
    categories = [
        ("IR・財務", prompt_fin, "財務・戦略"),
        ("PR・ニュース", prompt_pr, "広報・戦略"),
        ("ヒト・組織", prompt_hr, "人事・組織開発")
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
                    time.sleep(2)
                    resp = model.generate_content(fact_prompt)
                    cat_facts += f"\n◆ソース: {url}\n{resp.text}\n"
                    st.markdown(f"<div class='fact-log'><b>✅ 抽出・考察完了</b><br>{resp.text[:100]}...</div>", unsafe_allow_html=True)
                except Exception as e:
                    st.write(f"⚠️ 分析エラー: {e}")
            
            fact_logs_all[cat_name] = cat_facts
            status.update(label=f"🎯 {agent_name}担当の分析完了！", state="complete")

    # --- フェーズ2: コンテキスト・チェーン（冗長性排除）による長文生成 ---
    st.subheader("📊 最終統合レポート（物語と推論の構築）")
    
    integration_context = f"""
    【リサーチャーが収集した事実と考察一覧】
    ■ 財務・戦略ファクト\n{fact_logs_all.get("IR・財務", "")}
    ■ 広報・ニュースファクト\n{fact_logs_all.get("PR・ニュース", "")}
    ■ ヒト・組織ファクト\n{fact_logs_all.get("ヒト・組織", "")}
    """
    
    final_report_text = ""
    context_chain = ""
    
    with st.status("👑 編集長が文脈を引き継ぎ、重複を省きながら1章ずつ書き上げています...", expanded=True) as ed_status:
        for section_title, section_prompt in EDITOR_PROMPTS.items():
            st.write(f"✍️ {section_title} を執筆中...")
            
            prompt_ed = f"対象企業: {company}\n\n【これまでの執筆内容（重複解説を避けること）】\n{context_chain}\n\n【リサーチャーが収集した事実と考察一覧】\n{integration_context}\n\n【あなたの任務】\n{section_prompt}\n\n※厳守：上記の【これまでの執筆内容】を必ず読み、既に説明されたキーワードや概念を初めて登場したかのように重複して解説しないでください。文脈が自然に繋がるように続きを書いてください。"
            
            try:
                time.sleep(3)
                sec_resp = model.generate_content(prompt_ed)
                section_text = sec_resp.text
                final_report_text += f"## {section_title}\n\n{section_text}\n\n---\n\n"
                
                context_chain += f"【{section_title}】\n{section_text}\n\n"
            except Exception as e:
                st.error(f"{section_title}の執筆中にエラー: {e}")
                
        ed_status.update(label="🎉 圧倒的な厚みと一貫性を持つ最終レポートが完成しました！", state="complete")

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
