import streamlit as st
import google.generativeai as genai
import time
from docx import Document
from io import BytesIO
from duckduckgo_search import DDGS

# --- 初期設定 ---
st.set_page_config(page_title="高度企業分析AIエージェント", layout="wide")

st.sidebar.title("🛠️ 設定")
default_api_key = st.secrets.get("GEMINI_API_KEY", "")
api_key = st.sidebar.text_input("Gemini API Key", value=default_api_key, type="password")

# --- エージェントの定義と検索キーワード ---
# 🌟 修正ポイント1：検索結果がゼロにならないよう、キーワードをシンプルに厳選
AGENT_TASKS = {
    "business": {
        "query": "ビジネスモデル 最新",
        "desc": "業界構造・ビジネスモデル・収益の仕組み・最新トレンドを分析してください。"
    },
    "strategy": {
        "query": "決算 中期経営計画",
        "desc": "競合比較・SWOT分析を行い、独自の強みと課題を抽出してください。"
    },
    "culture": {
        "query": "採用 社員インタビュー",
        "desc": "採用サイトやインタビューから、活躍する社員像と求めるマインドセットを言語化してください。"
    },
    "career": {
        "query": "キャリア 転職 市場価値",
        "desc": "3年後から40歳までのキャリアパスと、各段階での市場価値を具体的に推論してください。"
    }
}

def search_latest_info(keyword):
    """DuckDuckGoで最新情報を検索し、テキストとしてまとめる関数"""
    try:
        with DDGS() as ddgs:
            # 🌟 修正ポイント2：地域を「日本(jp-jp)」に指定し、過去1年以内(y)の記事を優先取得する
            results = list(ddgs.text(keyword, region='jp-jp', timelimit='y', max_results=3))
        
        if not results:
            return "（※最新の検索結果が取得できなかったため、AIの既存知識のみで分析します）"
            
        context = "【最新のウェブ検索結果（日本語）】\n"
        for res in results:
            context += f"・{res.get('title', '')}\n  {res.get('body', '')}\n"
        return context
    except Exception as e:
        return f"検索中にエラーが発生しました: {e}"

def run_research_agent(company_name, task_info):
    search_keyword = f"{company_name} {task_info['query']}"
    search_context = search_latest_info(search_keyword)
    
    model = genai.GenerativeModel(model_name='gemini-3.1-flash-lite-preview')
    
    prompt = f"""
    対象企業: {company_name}
    
    以下の【最新のウェブ検索結果】をベースにしつつ、あなたの知識も補完的に使って指示に従ってください。
    
    {search_context}
    
    指示: {task_info['desc']}
    事実と推論を分けて、論理的に記述してください。
    """
    response = model.generate_content(prompt)
    
    return response.text, search_context

# --- メインUI ---
st.title("🔍 高度企業分析AIレポート生成 (最新Webリサーチ版)")
st.info("企業名を入力すると、裏側で自動的にWeb検索(日本限定)を行い、最新のIRやニュースを読み込んで分析します。")

company_name = st.text_input("分析したい企業名を入力してください（例：株式会社マクアケ）")

if st.button("🚀 分析を開始する"):
    if not api_key:
        st.error("APIキーを入力してください。")
    elif not company_name:
        st.error("企業名を入力してください。")
    else:
        genai.configure(api_key=api_key)
        
        report_results = {}
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        try:
            for i, (key, task_info) in enumerate(AGENT_TASKS.items()):
                status_text.text(f"⏳ エージェント [{key}] がWeb検索＆分析中...")
                
                ai_text, search_data = run_research_agent(company_name, task_info)
                report_results[key] = ai_text
                
                with st.expander(f"📊 {key.capitalize()} 分析結果", expanded=True):
                    st.markdown(ai_text)
                    st.caption("👇 この分析のためにAIが取得した最新Webデータ（証拠）")
                    st.code(search_data, language="text")
                
                progress_bar.progress((i + 1) / len(AGENT_TASKS))
                
                if i < len(AGENT_TASKS) - 1:
                    time.sleep(5)
            
            status_text.success("✅ 全エージェントの最新リサーチが完了しました！")
            
            # --- 簡易Word出力 ---
            doc = Document()
            doc.add_heading(f"{company_name} 企業研究レポート", 0)
            for key, content in report_results.items():
                doc.add_heading(key.capitalize(), level=1)
                doc.add_paragraph(content)
                
            bio = BytesIO()
            doc.save(bio)
            st.download_button(
                label="📄 Wordレポートをダウンロード",
                data=bio.getvalue(),
                file_name=f"{company_name}_最新レポート.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
        except Exception as e:
            st.error(f"⚠️ 分析中にエラーが発生しました: {e}")
