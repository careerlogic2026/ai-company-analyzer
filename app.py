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
    .date-badge { background-color: #28a745; color: white; padding: 2px 6px; border-radius: 4px; font-size: 0.8em; margin-right: 8px; font-weight: bold; }
    .badge-pr { background-color: #007bff; color: white; padding: 2px 6px; border-radius: 4px; font-size: 0.8em; margin-right: 8px; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

st.sidebar.title("🛠️ API設定")
gemini_key = st.sidebar.text_input("Gemini API Key", value=st.secrets.get("GEMINI_API_KEY", ""), type="password")
tavily_key = st.sidebar.text_input("Tavily API Key", value=st.secrets.get("TAVILY_API_KEY", ""), type="password")

if "search_done" not in st.session_state: st.session_state.search_done = False
if "research_done" not in st.session_state: st.session_state.research_done = False
if "search_results" not in st.session_state: st.session_state.search_results = {}

# ==========================================
# 1. ツール関数
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
# 2. プロンプト定義
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
    "1. 業界構造とビジネスモデル": "提供された全ファクトを用いて、『1. 業界構造とビジネスモデル』の章を1000文字以上で執筆してください。\n読者が『この会社がどのようなエコシステムで稼いでいるのか』を構造的に理解できるよう、AIのビジネス知見で補完しながら重厚に解説してください。具体的な数値や強みを含めること。",
    "2. 事業分析（収益構造と最新動向）": "提供された全ファクトを用いて、『2. 事業分析（収益構造と最新動向）』の章を1000文字以上で執筆してください。\n過去からの成り立ち、現在仕込んでいるPRや提携（最新動向）、そして未来への流れという「時間軸（進化論）」を意識して、一つの物語として記述してください。",
    "3. 競合比較・SWOT分析": "提供された全ファクトを用いて、『3. 競合比較・SWOT分析』の章を1000文字以上で執筆してください。\nこの会社が現在直面している「最大の経営課題（ボトルネック）」を中心に据え、それを乗り越えるための強み（S）と弱み（W）を深く分析してください。",
    "4. 組織にいる人材と求める人物像": "提供された全ファクトを用いて、『4. 組織にいる人材と求める人物像』の章を1000文字以上で執筆してください。\nリサーチャーが挙げた「実在の社員名と個別エピソード」を必ずすべて本文に組み込み、彼らが経営課題をどう解決しているかを描写してください。",
    "5. キャリアパスと市場価値推論": "提供された全ファクトを用いて、『5. キャリアパスと市場価値推論』の章を1000文字以上で執筆してください。\nこれまでの第1〜4章のロジックを統合し、「この会社で3年働くと、どのような独自スキルが身につき、30歳時点で転職市場においてどの業界から、どの程度の想定年収でスカウトされるか」をエビデンスに基づいて推論してください。"
}

# ==========================================
# UIセクション 1: 入力とハイブリッド検索
# ==========================================
st.title("🎯 真・高度企業分析: マルチエージェント・ディープリサーチ")
st.write("確実な戦略情報と、網羅的に収集した最新ニュース・社員記事を統合し、圧倒的な熱量のレポートを生成します。")

company = st.text_input("🏢 企業名", value="株式会社マクアケ")

st.subheader("📊 1-A. 【確実性担保】最重要ファクトの直接指定（IR・ビジョン等）")
ir_urls_input = st.text_area(
    "上場企業の場合は「最新の決算説明会資料」等のPDFリンクを、未上場企業の場合は「コーポレートサイトのVision/Mission」や「社長インタビュー記事」のURLを改行で入力してください。",
    value="https://pdf.irpocket.com/C4477/yD3U/v5c7/O11m.pdf\n", 
    height=100
)

st.subheader("🌐 1-B. 【網羅的抽出】メディア・採用ページの指定")
col1, col2 = st.columns(2)
with col1:
    pr_url = st.text_input("PR TIMES URL", value="https://prtimes.jp/main/html/searchrlp/company_id/36381")
with col2:
    rec_url = st.text_input("Wantedly URL", value="https://www.wantedly.com/companies/makuake")

if st.button("🔍 1. 対象メディアから最新・重要記事を抽出", type="primary"):
    if not tavily_key: st.error("サイドバーにTavily APIキーを設定してください。"); st.stop()
    
    with st.spinner("PR TIMESからの最新記事直取り、およびTavily AIによる年号指定検索を実行中..."):
        client = TavilyClient(api_key=tavily_key)
        results = {"IR・財務": [], "PR・ニュース": [], "ヒト・組織": []}
        
        short_company = company.replace("株式会社", "").replace("合同会社", "").strip()
        
        # 年号ハック用の変数作成（直近3年）
        current_year = datetime.date.today().year
        recent_years = f"({current_year} OR {current_year-1} OR {current_year-2})"
        
        try:
            # ==============================================
            # 1. 財務・戦略 (手動入力URL)
            # ==============================================
            ir_urls = [u.strip() for u in ir_urls_input.split('\n') if u.strip()]
            for i, url in enumerate(ir_urls):
                results["IR・財務"].append({"title": f"指定された重要資料 ({i+1})", "url": url, "date_str": "手動指定"})
            
            # ==============================================
            # 2. PR・ニュース (検索エンジン飛ばし：直取りハック)
            # ==============================================
            pr_id_match = re.search(r'company_id/(\d+)', pr_url) if pr_url else None
            pr_id = pr_id_match.group(1) if pr_id_match else None
            filtered_pr = []
            
            if pr_id:
                try:
                    # 企業ページを直接スクレイピングして、上から順に取得（絶対最新順）
                    res = requests.get(pr_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                    soup = BeautifulSoup(res.text, 'html.parser')
                    
                    seen_urls = set()
                    # 記事リンクを抽出
                    for a in soup.find_all('a', href=re.compile(fr'/main/html/rd/p/.*\.*{pr_id}\.html')):
                        url = "https://prtimes.jp" + a['href']
                        title = a.get_text(strip=True)
                        
                        if url not in seen_urls and len(title) > 5:
                            seen_urls.add(url)
                            filtered_pr.append({
                                "title": title, 
                                "url": url, 
                                "date_str": "公式・最新"
                            })
                            if len(filtered_pr) >= 30: # 最新30件でストップ
                                break
                except Exception as e:
                    st.write(f"PR直取りスキップ: {e}")
            
            results["PR・ニュース"] = filtered_pr
            
            # ==============================================
            # 3. ヒト・組織 (年号ハック ＆ URL絶対信頼フィルタ)
            # ==============================================
            rec_slug_match = re.search(r'companies/([^/]+)', rec_url) if rec_url else None
            rec_slug = rec_slug_match.group(1) if rec_slug_match else None
            
            hr_domains = ["wantedly.com", "note.com", "talentbook.jp", "prtimes.jp", "fastgrow.jp"]
            # クエリに年号を追加し、古い記事を検索エンジンレベルで弾く
            q_hr = f"{short_company} インタビュー OR 採用 OR カルチャー OR 社員 {recent_years}"
            
            raw_hr = client.search(
                query=q_hr, 
                include_domains=hr_domains, 
                max_results=100
            ).get("results", [])
            
            filtered_hr = []
            bad_words = ["株価", "投資", "業績", "決算", "予想", "分析"]
            
            for r in raw_hr:
                url_lower = r["url"].lower()
                title_content = (r.get("title", "") + r.get("content", "")).lower()
                
                # ノイズキャンセリング
                if any(bw in title_content for bw in bad_words):
                    continue
                
                is_valid = False
                # ドメインごとの判定（URLで担保できるものは社名チェックを免除＝激減防止）
                if "wantedly.com" in url_lower:
                    if ("post_articles" in url_lower or "stories" in url_lower) and (not rec_slug or rec_slug.lower() in url_lower):
                        is_valid = True
                elif "prtimes.jp" in url_lower:
                    if "/story/" in url_lower:
                        is_valid = True
                else:
                    # note等の外部メディアは、念のため社名チェックを実施
                    if short_company.lower() in title_content:
                        is_valid = True
                
                if is_valid:
                    # スニペットから日付を引っこ抜く
                    date_match = re.search(r'(202[0-9])[年/.-](1[0-2]|0?[1-9])[月/.-](3[01]|[12][0-9]|0?[1-9])', r.get("content", ""))
                    if date_match:
                        y, m, d = date_match.groups()
                        r["date_str"] = f"{y}年{int(m)}月{int(d)}日"
                        r["sort_key"] = int(f"{y}{int(m):02d}{int(d):02d}")
                    else:
                        id_match = re.search(r'(?:post_articles|stories|story|n)/0*([a-zA-Z0-9]+)', url_lower)
                        r["sort_key"] = 0 # 日付不明
                        r["date_str"] = "直近3年内"
                    
                    filtered_hr.append(r)
                    
            # 日付が大きい順に並べ替え！
            filtered_hr.sort(key=lambda x: x["sort_key"], reverse=True)
            results["ヒト・組織"] = filtered_hr[:30] # 30件を取得

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
    st.info("PRは公式ページから最新順に直接取得。HRは年号ハックにより直近記事を数十件確保しました。")
    
    selected_urls = {"IR・財務": [], "PR・ニュース": [], "ヒト・組織": []}
    tabs = st.tabs(list(st.session_state.search_results.keys()))

    for i, cat in enumerate(st.session_state.search_results.keys()):
        with tabs[i]:
            if not st.session_state.search_results[cat]:
                st.warning("対象記事が見つかりませんでした。")
            else:
                st.success(f"✅ {len(st.session_state.search_results[cat])}件の最新・重要記事が見つかりました！")
                
            for j, item in enumerate(st.session_state.search_results[cat]):
                # バッジの表示切り替え
                date_str = item.get('date_str', '')
                if "公式" in date_str or "手動" in date_str:
                    badge_html = f"<span class='badge-pr'>🚀 {date_str}</span>"
                elif date_str:
                    badge_html = f"<span class='date-badge'>📅 {date_str}</span>"
                else:
                    badge_html = ""
                
                st.markdown(f"<div class='source-card'>{badge_html} <b>{item['title']}</b><br><a href='{item['url']}' target='_blank'><small>{item['url']}</small></a></div>", unsafe_allow_html=True)
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
        ("IR・財務", PROMPT_FIN, "財務・戦略"),
        ("PR・ニュース", PROMPT_PR, "広報・戦略"),
        ("ヒト・組織", PROMPT_HR, "人事・組織開発")
    ]
    
    fact_logs_all = {}

    for cat_name, prompt_text, agent_name in categories:
        urls = st.session_state.selected_urls.get(cat_name, [])
        if not urls:
            fact_logs_all[cat_name] = "情報なし"
            continue
            
        with st.status(f"🕵️‍♂️ {agent_name}担当が事実の抽出と戦略的考察を実行中... (全{len(urls)}件)", expanded=True) as status:
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

    st.subheader("📊 最終統合レポート（物語と推論の構築）")
    
    integration_context = f"【リサーチャーが収集した事実と考察一覧】\n■ 財務・戦略ファクト\n{fact_logs_all.get('IR・財務', '')}\n■ 広報・ニュースファクト\n{fact_logs_all.get('PR・ニュース', '')}\n■ ヒト・組織ファクト\n{fact_logs_all.get('ヒト・組織', '')}"
    final_report_text = ""
    context_chain = ""
    
    with st.status("👑 編集長が文脈を引き継ぎ、重複を省きながら1章ずつ書き上げています...", expanded=True) as ed_status:
        for section_title, section_prompt in EDITOR_PROMPTS.items():
            st.write(f"✍️ {section_title} を執筆中...")
            
            prompt_ed = f"対象企業: {company
