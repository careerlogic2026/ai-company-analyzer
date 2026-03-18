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
import json

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
PROMPT_FIN = "あなたは超一流の財務・戦略リサーチャーです。以下の資料からファクト（事実）を抽出するだけでなく、プロの視点で「考察」を加えてください。※未上場企業の場合はビジョンや社長のメッセージを重視してください。\n【必須項目】1.収益モデル 2.経営課題 3.独自の強み"
PROMPT_PR = "あなたは敏腕ビジネス記者です。以下の記事から事実を抽出し、「企業の狙い」を考察してください。\n【必須項目】1.提携/新サービス 2.具体的実績 3.戦略的意図"
PROMPT_HR = "あなたは組織開発のプロです。以下の記事から組織のリアルを抽出・考察してください。\n【必須項目】1.実在の社員名とエピソード 2.ミッション 3.現場のマインドセット"

EDITOR_PROMPTS = {
    "1. 業界構造とビジネスモデル": "1000文字以上で執筆。収益モデルを重厚に解説。",
    "2. 事業分析（収益構造と最新動向）": "1000文字以上で執筆。時間軸（進化論）を意識。",
    "3. 競合比較・SWOT分析": "1000文字以上で執筆。経営課題を中心に分析。",
    "4. 組織にいる人材と求める人物像": "1000文字以上で執筆。実在の社員名とエピソードをすべて組み込むこと。",
    "5. キャリアパスと市場価値推論": "1000文字以上で執筆。30歳時点の想定年収とスカウト業界を具体的に推論。"
}

# ==========================================
# UIセクション 1: 入力
# ==========================================
st.title("🎯 真・高度企業分析: マルチエージェント・ディープリサーチ")
company = st.text_input("🏢 企業名", value="株式会社マクアケ")

st.subheader("📊 1-A. 【確実性担保】最重要ファクトの直接指定（IR・ビジョン等）")
ir_urls_input = st.text_area("最新のPDFリンク等を改行で入力してください。", value="https://pdf.irpocket.com/C4477/yD3U/v5c7/O11m.pdf", height=80)

st.subheader("🌐 1-B. 【網羅的抽出】メディア・採用ページの指定")
col1, col2 = st.columns(2)
with col1: pr_url = st.text_input("PR TIMES URL", value="https://prtimes.jp/main/html/searchrlp/company_id/36381")
with col2: rec_url = st.text_input("Wantedly URL", value="https://www.wantedly.com/companies/makuake")

if st.button("🔍 1. AIフィルタリングによる高品質リサーチを開始", type="primary"):
    if not tavily_key or not gemini_key: st.error("APIキーを設定してください。"); st.stop()
    
    genai.configure(api_key=gemini_key)
    # フィルタリング用の高速モデル
    model_flash = genai.GenerativeModel('gemini-1.5-flash')
    client = TavilyClient(api_key=tavily_key)
    
    with st.spinner("Web全域から収集し、AIが『鮮度』と『質』で記事を厳選しています..."):
        results = {"IR・財務": [], "PR・ニュース": [], "ヒト・組織": []}
        short_company = company.replace("株式会社", "").replace("合同会社", "").strip()
        
        # 1. IR (手動入力)
        for u in ir_urls_input.split('\n'):
            if u.strip(): results["IR・財務"].append({"title": "指定重要資料", "url": u.strip(), "date_str": "手動指定"})
            
        # 2. PR & 3. HR (AIフィルタリング案3)
        search_queries = [
            ("PR・ニュース", f'"{short_company}" プレスリリース OR 提携 OR 取材', ["prtimes.jp", "nikkei.com", "newspicks.com", "itmedia.co.jp"]),
            ("ヒト・組織", f'"{short_company}" インタビュー OR 社員 OR 採用 OR カルチャー', ["wantedly.com", "note.com", "talentbook.jp", "fastgrow.jp"])
        ]
        
        for cat_name, q, domains in search_queries:
            # A. 雑に100件取得
            raw_hits = client.search(query=q, include_domains=domains, max_results=80).get("results", [])
            
            # B. AIに渡すリストの作成
            hit_list_text = ""
            for i, h in enumerate(raw_hits):
                hit_list_text += f"[{i}] Title: {h['title']}\nSnippet: {h['content']}\n\n"
            
            # C. AIによる目利き
            filter_prompt = f"""あなたはプロのリサーチャーです。以下の「{short_company}」に関する検索結果から、**「直近1〜2年（2024年〜2026年）の最新記事」**かつ**「情報価値が高い（戦略や人物像が深くわかる）」**ものを最大30件選び、その【番号のみ】をカンマ区切りのリストで返してください。
            ※他社の情報は厳禁。2023年以前の記事は原則除外。
            【検索結果】
            {hit_list_text}"""
            
            try:
                res = model_flash.generate_content(filter_prompt)
                valid_indices = [int(idx.strip()) for idx in re.findall(r'\d+', res.text)]
                
                filtered_list = []
                for idx in valid_indices:
                    if idx < len(raw_hits):
                        hit = raw_hits[idx]
                        # 日付抽出
                        date_match = re.search(r'(202[4-6])[年/.-](1[0-2]|0?[1-9])[月/.-](3[01]|[12][0-9]|0?[1-9])', hit['content'])
                        hit['date_str'] = date_match.group(0) if date_match else "2024-2026(AI判定)"
                        hit['sort_key'] = int(re.sub(r'\D', '', hit['date_str'])) if date_match else 0
                        filtered_list.append(hit)
                
                # 最新順ソート
                filtered_list.sort(key=lambda x: x['sort_key'], reverse=True)
                results[cat_name] = filtered_list[:30]
            except Exception as e:
                st.warning(f"{cat_name}のフィルタリングでエラー: {e}")
                results[cat_name] = raw_hits[:15] # 失敗時は上位をそのまま

        st.session_state.search_results = results
        st.session_state.search_done = True
        st.rerun()

# ==========================================
# UIセクション 2: ソース選択
# ==========================================
if st.session_state.search_done:
    st.subheader("📚 2. AIが厳選した最新・高品質記事（最大30件）")
    selected_urls = {"IR・財務": [], "PR・ニュース": [], "ヒト・組織": []}
    tabs = st.tabs(list(st.session_state.search_results.keys()))

    for i, cat in enumerate(st.session_state.search_results.keys()):
        with tabs[i]:
            for j, item in enumerate(st.session_state.search_results[cat]):
                st.markdown(f"<div class='source-card'><span class='date-badge'>📅 {item.get('date_str','最新')}</span> <b>{item['title']}</b><br><small>{item['url']}</small></div>", unsafe_allow_html=True)
                if st.checkbox("精読対象に含める", key=f"chk_{cat}_{j}", value=True):
                    selected_urls[cat].append(item['url'])

    if st.button("🚀 3. レポート執筆を開始", type="primary"):
        st.session_state.selected_urls = selected_urls
        st.session_state.research_done = True
        st.rerun()

# ==========================================
# UIセクション 3: リサーチ実行とレポート生成
# ==========================================
if st.session_state.research_done:
    st.subheader("🧠 3. 分析・執筆プロセス")
    genai.configure(api_key=gemini_key)
    model = genai.GenerativeModel('gemini-3.1-flash-lite-preview')
    
    # フェーズ1: 抽出
    fact_logs = {}
    for cat_name, prompt, agent_name in [("IR・財務", PROMPT_FIN, "財務"), ("PR・ニュース", PROMPT_PR, "広報"), ("ヒト・組織", PROMPT_HR, "組織")]:
        urls = st.session_state.selected_urls.get(cat_name, [])
        with st.status(f"🕵️‍♂️ {agent_name}担当が{len(urls)}件の記事を精読中...") as status:
            combined_facts = ""
            for url in urls:
                text = extract_text_from_url(url)
                resp = model.generate_content(f"企業:{company}\nソース:{url}\n内容:{text}\n任務:{prompt}")
                combined_facts += f"\n◆{url}\n{resp.text}\n"
            fact_logs[cat_name] = combined_facts
            status.update(label=f"🎯 {agent_name}担当の分析完了", state="complete")

    # フェーズ2: リレー執筆（冗長性排除）
    st.subheader("📊 最終統合レポート")
    all_facts = f"【財務】\n{fact_logs.get('IR・財務')}\n【広報】\n{fact_logs.get('PR・ニュース')}\n【組織】\n{fact_logs.get('ヒト・組織')}"
    final_text = ""
    context_chain = ""
    with st.status("👑 編集長が文脈を繋ぎながら執筆中...") as status:
        for title, prompt in EDITOR_PROMPTS.items():
            st.write(f"✍️ {title} を生成中...")
            full_p = f"企業:{company}\n事実:{all_facts}\n既出内容:{context_chain}\n章:{title}\n指示:{prompt}\n※既出の解説は繰り返さず続きを書け。"
            res = model.generate_content(full_p)
            final_text += f"## {title}\n\n{res.text}\n\n---\n\n"
            context_chain += f"\n[{title}]\n{res.text[:500]}...\n"
        status.update(label="🎉 レポート完成！", state="complete")

    st.markdown(final_text)
    # Wordダウンロード
    doc = Document(); doc.add_heading(f"{company} 企業研究", 0)
    for p in final_text.split('\n'):
        if p.startswith('## '): doc.add_heading(p[3:], 1)
        elif p.strip() and p != "---": doc.add_paragraph(p)
    bio = BytesIO(); doc.save(bio)
    st.download_button("📄 Wordで保存", data=bio.getvalue(), file_name=f"{company}_DeepReport.docx", type="primary")
