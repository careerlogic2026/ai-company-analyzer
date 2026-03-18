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
PROMPT_FIN = "あなたは財務・戦略リサーチャーです。事実から『経営課題』と『独自の強み』を抽出・考察してください。"
PROMPT_PR = "あなたはビジネス記者です。提携や新サービスから『企業の戦略的意図』を抽出・考察してください。"
PROMPT_HR = "あなたは組織開発のプロです。実在の社員エピソードから『現場のマインドセット』を抽出・考察してください。"

EDITOR_PROMPTS = {
    "1. 業界構造とビジネスモデル": "1000文字以上で執筆。収益構造を重厚に解説。",
    "2. 事業分析（収益構造と最新動向）": "1000文字以上で執筆。最新の動きを軸に展開。",
    "3. 競合比較・SWOT分析": "1000文字以上で執筆。ボトルネックを深掘り。",
    "4. 組織にいる人材と求める人物像": "1000文字以上で執筆。抽出された全社員名を組み込む。",
    "5. キャリアパスと市場価値推論": "1000文字以上で執筆。具体的な市場評価を推論。"
}

# ==========================================
# UIセクション 1: 入力
# ==========================================
st.title("🎯 高度企業分析AI: ハイブリッド・リサーチエンジン")
company = st.text_input("🏢 企業名", value="株式会社マクアケ")

st.subheader("📊 1-A. 最重要ファクト指定（IR等）")
ir_urls_input = st.text_area("最新のPDFリンク等を入力してください。", value="https://pdf.irpocket.com/C4477/yD3U/v5c7/O11m.pdf", height=80)

st.subheader("🌐 1-B. メディア・採用ページ指定")
col1, col2 = st.columns(2)
with col1: pr_url = st.text_input("PR TIMES URL", value="https://prtimes.jp/main/html/searchrlp/company_id/36381")
with col2: rec_url = st.text_input("Wantedly URL", value="https://www.wantedly.com/companies/makuake")

if st.button("🔍 1. 最新順・ドメイン分割検索を実行", type="primary"):
    if not tavily_key: st.error("APIキーを設定してください。"); st.stop()
    
    client = TavilyClient(api_key=tavily_key)
    now = datetime.datetime.now()
    years_query = f"({now.year} OR {now.year - 1})"
    short_company = company.replace("株式会社", "").replace("合同会社", "").strip()

    with st.spinner(f"{years_query}の最新記事をドメインごとに一本釣りしています..."):
        results = {"IR・財務": [], "PR・ニュース": [], "ヒト・組織": []}
        
        # 1. IR (手動入力)
        for u in ir_urls_input.split('\n'):
            if u.strip(): results["IR・財務"].append({"title": "指定資料", "url": u.strip(), "date_str": "手動"})

        # ==========================================
        # 2. PR検索 (PR TIMES + 経済メディア)
        # ==========================================
        pr_id_match = re.search(r'company_id/(\d+)', pr_url) if pr_url else None
        pr_id = pr_id_match.group(1) if pr_id_match else ""
        
        # クエリ1: PR TIMES公式
        q_pr1 = f"{short_company} {years_query}"
        res_pr1 = client.search(query=q_pr1, include_domains=["prtimes.jp"], max_results=40).get("results", [])
        
        # クエリ2: 経済メディア
        q_pr2 = f"{short_company} (提携 OR 取材 OR 新機能) {years_query}"
        res_pr2 = client.search(query=q_pr2, include_domains=["nikkei.com", "newspicks.com", "itmedia.co.jp"], max_results=40).get("results", [])
        
        combined_pr = res_pr1 + res_pr2
        seen_pr = set()
        for r in combined_pr:
            if r["url"] not in seen_pr:
                # PR TIMESの場合、IDチェック
                if "prtimes.jp" in r["url"] and pr_id and pr_id not in r["url"]: continue
                seen_pr.add(r["url"])
                # 日付抽出
                d = re.search(r'(202[4-6])[年/.-](1[0-2]|0?[1-9])[月/.-](3[01]|[12][0-9]|0?[1-9])', r['content'])
                r['date_str'] = d.group(0) if d else f"{now.year}年推測"
                results["PR・ニュース"].append(r)
        results["PR・ニュース"].sort(key=lambda x: x.get('date_str',''), reverse=True)

        # ==========================================
        # 3. ヒト検索 (Wantedly + note/採用メディア)
        # ==========================================
        rec_slug_match = re.search(r'companies/([^/]+)', rec_url) if rec_url else None
        rec_slug = rec_slug_match.group(1) if rec_slug_match else ""

        # クエリ1: Wantedly
        q_hr1 = f"{short_company} {years_query}"
        res_hr1 = client.search(query=q_hr1, include_domains=["wantedly.com"], max_results=50).get("results", [])

        # クエリ2: note / 採用メディア
        q_hr2 = f"{short_company} (インタビュー OR 社員 OR 採用) {years_query}"
        res_hr2 = client.search(query=q_hr2, include_domains=["note.com", "talentbook.jp", "fastgrow.jp"], max_results=50).get("results", [])

        combined_hr = res_hr1 + res_hr2
        seen_hr = set()
        for r in combined_hr:
            if r["url"] not in seen_hr:
                # Wantedlyの場合、スラッグと記事形式チェック
                if "wantedly.com" in r["url"]:
                    if rec_slug and rec_slug not in r["url"]: continue
                    if not ("post_articles" in r["url"] or "stories" in r["url"]): continue
                seen_hr.add(r["url"])
                d = re.search(r'(202[4-6])[年/.-](1[0-2]|0?[1-9])[月/.-](3[01]|[12][0-9]|0?[1-9])', r['content'])
                r['date_str'] = d.group(0) if d else f"{now.year}年推測"
                results["ヒト・組織"].append(r)
        results["ヒト・組織"].sort(key=lambda x: x.get('date_str',''), reverse=True)

        st.session_state.search_results = results
        st.session_state.search_done = True
        st.rerun()

# ==========================================
# UIセクション 2: ソース選択
# ==========================================
if st.session_state.search_done:
    st.subheader("📚 2. 最新順・ドメイン分割抽出結果（各カテゴリ最大40-50件）")
    selected_urls = {"IR・財務": [], "PR・ニュース": [], "ヒト・組織": []}
    tabs = st.tabs(list(st.session_state.search_results.keys()))

    for i, cat in enumerate(st.session_state.search_results.keys()):
        with tabs[i]:
            st.success(f"{len(st.session_state.search_results[cat])}件の候補を表示中")
            for j, item in enumerate(st.session_state.search_results[cat]):
                st.markdown(f"<div class='source-card'><span class='date-badge'>📅 {item.get('date_str')}</span> <b>{item['title']}</b><br><small>{item['url']}</small></div>", unsafe_allow_html=True)
                if st.checkbox("含める", key=f"chk_{cat}_{j}", value=True):
                    selected_urls[cat].append(item['url'])

    if st.button("🚀 3. 戦略的分析・レポート執筆開始", type="primary"):
        st.session_state.selected_urls = selected_urls
        st.session_state.research_done = True
        st.rerun()

# ==========================================
# UIセクション 3: 分析 & レポート
# ==========================================
if st.session_state.research_done:
    st.subheader("🧠 3. 分析・執筆プロセス")
    genai.configure(api_key=gemini_key)
    model = genai.GenerativeModel('gemini-3.1-flash-lite-preview')
    
    fact_logs = {}
    for cat_name, p_text, agent in [("IR・財務", PROMPT_FIN, "財務"), ("PR・ニュース", PROMPT_PR, "広報"), ("ヒト・組織", PROMPT_HR, "組織")]:
        urls = st.session_state.selected_urls.get(cat_name, [])
        with st.status(f"🕵️‍♂️ {agent}担当が{len(urls)}件を分析中...") as status:
            combined = ""
            for url in urls:
                t = extract_text_from_url(url)
                res = model.generate_content(f"ソース:{url}\n内容:{t}\n指示:{p_text}")
                combined += f"\n◆{url}\n{res.text}\n"
            fact_logs[cat_name] = combined
            status.update(label=f"🎯 {agent}分析完了", state="complete")

    st.subheader("📊 最終統合レポート")
    all_facts = "\n".join(fact_logs.values())
    final_text = ""
    chain = ""
    with st.status("👑 編集長が執筆中...") as status:
        for title, prompt in EDITOR_PROMPTS.items():
            st.write(f"✍️ {title} を生成中...")
            res = model.generate_content(f"事実:{all_facts}\n既出:{chain}\n任務:{prompt}")
            final_text += f"## {title}\n\n{res.text}\n\n---\n\n"
            chain += f"[{title}]\n{res.text[:300]}...\n"
        status.update(label="🎉 レポート完成！", state="complete")

    st.markdown(final_report_text := final_text)
    doc = Document(); doc.add_heading(f"{company} 研究", 0)
    for p in final_text.split('\n'):
        if p.startswith('## '): doc.add_heading(p[3:], 1)
        elif p.strip() and p != "---": doc.add_paragraph(p)
    bio = BytesIO(); doc.save(bio)
    st.download_button("📄 Word保存", data=bio.getvalue(), file_name="Report.docx", type="primary")
