import streamlit as st
import google.generativeai as genai
import json
import time  # 🌟 追加：時間をコントロールするための道具
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
    model = genai.GenerativeModel(
        model_name='gemini-3.1-flash-lite-preview', 
        tools='google_search_retrieval' 
    )
    prompt = f"対象企業: {company_name}\n指示: {task_description}\n必ず最新のIR情報やプレスリリースを確認し、事実と推論を分けて記述してください。"
    response = model.generate_content(prompt)
    return response.text

# --- メインUI ---
st.title("🔍 高度企業分析AIレポート生成")
st.info("企業名を入力すると、4つの専門家エージェントがネット上の最新情報をリサーチします。")

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
            # 各エージェントを順番に実行
            for i, (key, task) in enumerate(AGENT_TASKS.items()):
                status_text.text(f"⏳ エージェント [{key}] がリサーチ中... (Google検索を実行中)")
                results[key] = run_research_agent(company_name, task)
                progress_bar.progress((i + 1) / len(AGENT_TASKS))
                
                # 🌟 追加：次のエージェントが動く前に10秒間待機する（無料枠のエラー回避）
                if i < len(AGENT_TASKS) - 1:
                    status_text.text("☕ APIの制限を回避するため、10秒間待機しています...")
                    time.sleep(10)
            
            status_text.success("✅ 全エージェントのリサーチが完了しました！")
            
            # 結果を表示
            for key, content in results.items():
                with st.expander(f"📊 {key.capitalize()} 分析結果"):
                    st.markdown(content)
            
            # --- 簡易Word出力 ---
            doc = Document()
            doc.add_heading(f"{company_name} 企業研究レポート", 0)
            for key, content in results.items():
                doc.add_heading(key.capitalize(), level=1)
                doc.add_paragraph(content)
                
            bio = BytesIO()
            doc.save(bio)
            st.download_button(
                label="📄 Wordレポートをダウンロード",
                data=bio.getvalue(),
                file_name=f"{company_name}_レポート.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
        except Exception as e:
            st.error(f"⚠️ リサーチ中にエラーが発生しました: {e}")
