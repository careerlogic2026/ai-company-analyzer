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
st.set_page_config(page_title="AI企業分析スカウター", layout="wide")
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .source-card { background-color: white; padding: 12px; border-radius: 8px; border-left: 5px solid #007bff; margin-bottom: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    .type-badge { color: white; padding: 3px 6px; border-radius: 4px; font-size: 0.75em; margin-right: 8px; font-weight: bold; }
    .pdf-badge { background-color: #dc3545; }
    .web-badge { background-color: #17a2b8; }
    .date-badge { background-color: #28a745; color: white; padding: 3px 6px; border-radius: 4px; font-size: 0.75em; margin-right: 8px; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

st.sidebar.title("🛠️ APIキー設定")
gemini_key = st.sidebar.text_input("Gemini API Key", value=st.secrets.get("GEMINI_API_KEY", ""), type="password")
tavily_key = st.sidebar.text_input("Tavily API Key", value=st.secrets.get("TAVILY_API_KEY", ""), type="password")

if "discovery_done" not in st.session_state: st.session_state.discovery_done = False
if "analysis_done" not in st.session_state: st.session_state.analysis_done = False

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
        soup = BeautifulSoup(res.content, 'html.parser')
        for s in soup(['script', 'style', 'nav', 'header', 'footer']): s.decompose()
        return soup.get_text(separator='\n', strip=True)[:10000]
    except Exception: return "[読み取りスキップ]"

# ==========================================
# 2. プロンプト定義
# ==========================================
PROMPT_FIN = "あなたは財務・戦略リサーチャーです。事実から『経営課題』と『独自の強み』を抽出・考察してください。"
PROMPT_PR = "あなたはビジネス記者です。提携や新サービスから『企業の戦略的意図』を抽出・考察してください。"
PROMPT_HR = "あなたは組織開発のプロです。実在の社員エピソードから『現場のマインドセット』を抽出・考察してください。"

EDITOR_PROMPTS = {
    "1. 業界構造と多角的ビジネスモデル": "1500文字以上で執筆。公式サイトの事業紹介とIRの数字を融合させ、収益の仕組みを重厚に解説せよ。",
    "2. 事業進化論と最新戦略動向": "1500文字以上で執筆。沿革と直近のPR事例を繋ぎ、過去から未来への成長物語を描け。",
    "3. 組織文化とコア人材の生態": "1500文字以上で執筆。社員の実名エピソードを多数引用し、現場の『熱量』を言語化せよ。",
    "4. キャリア価値と市場評価の推論": "1500文字以上で執筆。30歳時点の具体的年収、スカウト業界、身につく専門性を徹底推論せよ。"
}

# ==========================================
# 3. UI: コントロールパネル（入力セクション）
# ==========================================
st.title("🎯 企業分析AI: ハイブリッド・スカウター")
st.write("「絶対外せない内部資料」は手動で確実に追加し、「大量の外部記事」はAIが自動探索するプロ仕様のツールです。")

company_name = st.text_input("🏢 企業名 (必須)", value="株式会社マクアケ")

st.markdown("### 📊 A. 【確実性重視】 最重要ファクト指定（IR・ビジョン等）")
ir_urls_input = st.text_area(
    "分析の核となる「決算説明会資料(PDF)」や「コーポレートのビジョンページ」のURLを改行で入力してください。",
    value="https://pdf.irpocket.com/C4477/yD3U/v5c7/O11m.pdf\n", 
    height=80
)

st.markdown("### 🌐 B. 【網羅性重視】 外部メディア・採用ページ探索設定")
col1, col2 = st.columns(2)
with col1:
    pr_url = st.text_input("📣 PR TIMES URL (任意・空白可)", value="https://prtimes.jp/main/html/searchrlp/company_id/36381")
with col2:
    rec_url = st.text_input("👥 Wantedly URL (任意・空白可)", value="https://www.wantedly.com/companies/makuake")

if st.button("🚀 デジタル資産のハイブリッド・スカウティングを開始", type="primary"):
    if not gemini_key or not tavily_key: st.error("APIキーを設定してください。"); st.stop()
    
    client = TavilyClient(api_key=tavily_key)
    short_name = company_name.replace("株式会社", "").replace("合同会社", "").strip()
    now = datetime.datetime.now()
    years = f"({now.year} OR {now.year-1} OR {now.year-2})"

    with st.spinner("指定された資料をセットし、Web全域からPRと社員インタビューを大量収集しています..."):
        results = {"A. 指定された重要資料 (内部/コア)": [], "B. 最新PR・メディア記事 (外部)": [], "C. 社員インタビュー・組織 (外部)": []}
        
        # --- A. 手動入力された資料のパース ---
        for i, u in enumerate(ir_urls_input.split('\n')):
            if u.strip():
                title = f"指定資料 {i+1} (PDF)" if u.lower().endswith('.pdf') else f"指定資料 {i+1} (WEB)"
                results["A. 指定された重要資料 (内部/コア)"].append({"title": title, "url": u.strip(), "date_str": "手動指定"})

        # --- B. PR・外部メディア探索 ---
        pr_id_match = re.search(r'company_id/(\d+)', pr_url) if pr_url else None
        pr_id = pr_id_match.group(1) if pr_id_match else ""
        
        q_pr1 = f"{short_name} プレスリリース {years}"
        res_pr1 = client.search(query=q_pr1, include_domains=["prtimes.jp"], max_results=50).get("results", [])
        q_pr2 = f"{short_name} (提携 OR 取材 OR ニュース) {years}"
        res_pr2 = client.search(query=q_pr2, include_domains=["nikkei.com", "xtrend.nikkei.com", "itmedia.co.jp", "bridge.jp.net", "newspicks.com"], max_results=50).get("results", [])
        
        seen_pr = set()
        for r in res_pr1 + res_pr2:
            if r["url"] not in seen_pr:
                if "prtimes.jp" in r["url"] and pr_id and pr_id not in r["url"]: continue
                seen_pr.add(r["url"])
                d = re.search(r'(202[4-6])[年/.-](1[0-2]|0?[1-9])[月/.-](3[01]|[12][0-9]|0?[1-9])', r['content'])
                r['date_str'] = d.group(0) if d else f"{now.year}年推測"
                results["B. 最新PR・メディア記事 (外部)"].append(r)
        results["B. 最新PR・メディア記事 (外部)"].sort(key=lambda x: x.get('date_str',''), reverse=True)

        # --- C. ヒト・組織探索 ---
        rec_slug_match = re.search(r'companies/([^/]+)', rec_url) if rec_url else None
        rec_slug = rec_slug_match.group(1) if rec_slug_match else short_name

        q_hr1 = f'"{short_name}" site:wantedly.com/companies/{rec_slug} (post_articles OR stories)'
        res_hr1 = client.search(query=q_hr1, max_results=50).get("results", [])
        
        q_hr2 = f"{short_name} (インタビュー OR 社員) {years}"
        res_hr2 = client.search(query=q_hr2, include_domains=["note.com", "talentbook.jp", "fastgrow.jp"], max_results=50).get("results", [])

        seen_hr = set()
        for r in res_hr1 + res_hr2:
            if r["url"] not in seen_hr:
                if "wantedly.com" in r["url"] and not ("post_articles" in r["url"] or "stories" in r["url"]): continue
                seen_hr.add(r["url"])
                d = re.search(r'(202[4-6])[年/.-](1[0-2]|0?[1-9])[月/.-](3[01]|[12][0-9]|0?[1-9])', r['content'])
                r['date_str'] = d.group(0) if d else f"{now.year}年推測"
                results["C. 社員インタビュー・組織 (外部)"].append(r)
        results["C. 社員インタビュー・組織 (外部)"].sort(key=lambda x: x.get('date_str',''), reverse=True)

        st.session_state.discovery_results = results
        st.session_state.discovery_done = True
        st.session_state.analysis_done = False
        st.rerun()

# ==========================================
# 4. UI: アコーディオン式サイトマップ
# ==========================================
if st.session_state.discovery_done and not st.session_state.analysis_done:
    st.divider()
    st.markdown("### 📋 構築された分析リスト（取捨選択）")
    st.info("AIが収集・整理した情報群です。各カテゴリをクリックして展開し、分析に含めたい資料にチェックを入れてください。")
    
    selected_data = []

    for cat_label, hits in st.session_state.discovery_results.items():
        with st.expander(f"🔻 {cat_label} (計 {len(hits)} 件)", expanded=True if "A." in cat_label else False):
            if not hits:
                st.write("該当する情報が見つかりませんでした。")
            for j, hit in enumerate(hits):
                is_pdf = hit['url'].lower().endswith('.pdf')
                t_badge = f"<span class='type-badge pdf-badge'>PDF</span>" if is_pdf else f"<span class='type-badge web-badge'>WEB</span>"
                d_badge = f"<span class='date-badge'>📅 {hit.get('date_str', '常設')}</span>" if hit.get('date_str') else ""
                
                st.markdown(f"<div class='source-card'>{t_badge} {d_badge} <b>{hit['title']}</b><br><a href='{hit['url']}' target='_blank'><small>{hit['url']}</small></a></div>", unsafe_allow_html=True)
                
                # 指定資料(A)は全てON、それ以外(B,C)は上位5件をON
                default_check = True if ("A." in cat_label) or (j < 5) else False
                if st.checkbox("分析に含める", key=f"chk_{cat_label}_{j}", value=default_check):
                    selected_data.append({"url": hit['url'], "title": hit['title'], "cat": cat_label})

    if st.button("🚀 選択した資料群でディープ分析を開始", type="primary"):
        if not selected_data: st.error("最低1つの資料を選択してください。")
        else:
            st.session_state.final_sources = selected_data
            st.session_state.analysis_done = True
            st.rerun()

# ==========================================
# 5. UI: 分析実行セクション
# ==========================================
if st.session_state.analysis_done:
    st.divider()
    genai.configure(api_key=gemini_key)
    model = genai.GenerativeModel('gemini-3.1-flash-lite-preview')
    
    with st.status("🧠 マルチエージェントによる深層読解とレポート編纂中...", expanded=True) as status:
        # ステップ1: 事実抽出
        all_content = ""
        for i, source in enumerate(st.session_state.final_sources):
            st.write(f"📖 読解中({i+1}/{len(st.session_state.final_sources)}): {source['title'][:30]}...")
            text = extract_text_from_url(source['url'])
            
            if "A." in source['cat']: p_task = PROMPT_FIN
            elif "B." in source['cat']: p_task = PROMPT_PR
            else: p_task = PROMPT_HR
            
            res = model.generate_content(f"資料:{source['title']}\n内容:{text}\n任務:{p_task}\n※事実に基づき具体的に考察せよ。")
            all_content += f"\n--- {source['title']} ---\n{res.text}\n"

        # ステップ2: リレー執筆
        report_md = ""
        context = ""
        for title, prompt in EDITOR_PROMPTS.items():
            st.write(f"🖋️ {title} を執筆中...")
            final_res = model.generate_content(f"事実データ:{all_content}\n既出内容:{context}\n章タイトル:{title}\n指示:{prompt}\n※プロのコンサルタントとして、重複を避け、圧倒的な熱量と論理で執筆せよ。")
            report_md += f"## {title}\n\n{final_res.text}\n\n---\n\n"
            context += f"【{title}要約】\n{final_res.text[:400]}...\n"
            
        status.update(label="🎉 究極の分析レポートが完成しました！", state="complete")

    st.markdown(report_md)
    
    # Word出力
    doc = Document(); doc.add_heading(f"{company_name} 分析レポート", 0)
    for p in report_md.split('\n'):
        if p.startswith('## '): doc.add_heading(p[3:], 1)
        elif p.strip() and p != "---": doc.add_paragraph(p)
    bio = BytesIO(); doc.save(bio)
    st.download_button("📄 レポート(Word)を保存", data=bio.getvalue(), file_name=f"{company_name}_Report.docx", type="primary")
    
    if st.button("🔄 最初からやり直す"):
        st.session_state.discovery_done = False
        st.session_state.analysis_done = False
        st.rerun()
