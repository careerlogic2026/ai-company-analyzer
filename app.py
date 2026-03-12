import streamlit as st
import google.generativeai as genai
import time
from docx import Document
from io import BytesIO

# --- 初期設定 ---
st.set_page_config(page_title="高度企業分析AIエージェント", layout="wide")

st.sidebar.title("🛠️ 設定")
default_api_key = st.secrets.get("GEMINI_API_KEY", "")
api_key = st.sidebar.text_input("Gemini API Key", value=default_api_key, type="password")

# --- エージェントの定義 ---
AGENT_TASKS = {
    "business": "業界構造・ビジネスモデル・収益の仕組み・最新トレンドを分析してください。",
    "strategy": "競合比較・SWOT分析を行い、独自の強みと課題を抽出してください。",
    "culture": "採用サイトやインタビューから、活躍する社員像と求めるマインドセットを言語化してください。",
    "career": "3年後から40歳までのキャリアパスと、各段階での市場価値を具体的に推論してください。"
}

def run_research_agent(company_name, task_description):
    # 🌟 修正ポイント：検索機能（tools）を削除し、AIが元々持っている知識で生成させます
    model = genai.GenerativeModel(
        model_name='gemini-1.5-flash'
    )
    prompt = f"対象企業: {company_name}\n指示: {task_description}\n事実と推論を分けて、論理的に記述してください。"
    response = model.generate_content(prompt)
    return response.text

# --- メインUI ---
st.title("🔍 高度企業分析AIレポート生成 (フェーズ1：検索なし版)")
st.info("企業名を入力すると、4つの専門家エージェントがAIの知識ベースからレポートを作成します。")

company_name = st.text_input("分析したい企業名を入力してください（例：株式会社マクアケ）")

if st.button("🚀 分析を開始する"):
    if not api_key:
        st.error("APIキーを入力してください。")
    elif not company_name:
        st.error("企業名を入力してください。")
    else:
        genai.configure(api_key=api_key)
        
        results = {}
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        try:
            for i, (key, task) in enumerate(AGENT_TASKS.items()):
                status_text.text(f"⏳ エージェント [{key}] が分析中...")
                results[key] = run_research_agent(company_name, task)
                progress_bar.progress((i + 1) / len(AGENT_TASKS))
                
                # 通常のAPI制限（1分間に15回）を安全にクリアするため、5秒だけ待機します
                if i < len(AGENT_TASKS) - 1:
                    status_text.text("☕ APIの制限を回避するため、5秒間待機しています...")
                    time.sleep(5)
            
            status_text.success("✅ 全エージェントの分析が完了しました！")
            
            # 結果を表示
            for key, content in results.items():
                with st.expander(f"📊 {key.capitalize()} 分析結果"):
                    st.markdown(content)
            
            # --- 簡易Word出力 ---
            doc = Document()
            doc.add_heading(f"{company_name} 企業研究レポート", 0)
            for key, content in results.items():
