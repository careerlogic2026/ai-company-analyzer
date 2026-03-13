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

# --- セッションステートの初期化 ---
if "search_done" not in st.session_state: st.session_state.search_done = False
if "research_done" not in st.session_state: st.session_state.research_done = False
if "search_results" not in st.session_state: st.session_state.search_results = {}

# ==========================================
# 1. ツール関数（情報抽出とディープリード）
# ==========================================
def extract_text_from_url(url):
    """URLからテキストを抽出（PDF/HTML両対応）"""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        if url.lower().endswith(".pdf"):
            res = requests.get(url, headers=headers, timeout=15)
            reader = PyPDF2.PdfReader(BytesIO(res.content))
            return "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])[:20000] # 最大2万文字
        
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        soup = BeautifulSoup(res.content, 'html.parser')
        for s in soup(['script', 'style', 'nav', 'header', 'footer']): s.decompose()
        return soup.get_text(separator='\n', strip=True)[:10000]
    except Exception as e:
        return f"[抽出スキップ: {e}]"

# --- デフォルトプロンプト ---
PROMPT_FIN = """あなたは財務・戦略リサーチャーです。以下の資料からファクト（事実）を箇条書きで抽出してください。
【必須抽出項目】①具体的な売上・利益の数値 ②収益モデルの仕組み ③経営陣が言及している注力施策 ④独自の強み
※推論は不要です。資料にある固有名詞や数値を絶対に漏らさずリスト化してください。"""

PROMPT_PR = """あなたは広報・ニュースリサーチャーです。以下の記事からファクト（事実）を箇条書きで抽出してください。
【必須抽出項目】①新サービス・業務提携の具体名 ②提携先企業名 ③リリースに記載されている具体的な実績（〇〇万ユーザー等）
※要約せず、具体的な名称をすべてリストアップしてください。"""

PROMPT_HR = """あなたは人事リサーチャーです。以下のインタビュー記事からファクト（事実）を箇条書きで抽出してください。
【必須抽出項目】①記事に登場する実在の社員名と役職 ②その人の
