import datetime # ファイル上部のimport群にこれがなければ追加してください

if st.button("🔍 1. 対象メディアから個別記事をリストアップ", type="primary"):
    if not tavily_key: st.error("サイドバーにTavily APIキーを設定してください。"); st.stop()
    
    with st.spinner("Tavily AIとPythonフィルタリングを用いて最新記事を抽出中..."):
        client = TavilyClient(api_key=tavily_key)
        results = {"IR・財務": [], "PR・ニュース": [], "ヒト・組織": []}
        
        # 直近1〜2年の年数を取得（例：2025 OR 2026）
        current_year = datetime.date.today().year
        recent_years = f"{current_year-1} OR {current_year}"
        
        try:
            # 1. IR情報の検索 (年数を強制付与して最新化)
            if hp_url:
                domain = urlparse(hp_url).netloc
                q_ir = f"{company} (決算説明資料 OR 中期経営計画 OR 統合報告書) {recent_years} site:{domain}"
                raw_ir = client.search(query=q_ir, max_results=10).get("results", [])
                # PDFを優先しつつ、最新の5件を取得
                results["IR・財務"] = raw_ir[:5]
            
            # 2. PR TIMESの検索 (広く検索し、Pythonで個別記事URLだけを抽出)
            if pr_url:
                pr_id_match = re.search(r'company_id/(\d+)', pr_url)
                pr_id = pr_id_match.group(1) if pr_id_match else ""
                
                # クエリはシンプルにドメインと企業名
                q_pr = f"{company} site:prtimes.jp"
                raw_pr = client.search(query=q_pr, max_results=20).get("results", [])
                
                # Python側でURL構造を厳格にチェック (/rd/p/ を含み、他社情報を排除)
                filtered_pr = []
                for r in raw_pr:
                    if "/main/html/rd/p/" in r["url"]:
                        if not pr_id or pr_id in r["url"]: # 企業IDがあればそれで絞る
                            filtered_pr.append(r)
                results["PR・ニュース"] = filtered_pr[:5]
                
            # 3. Wantedlyの検索 (広く検索し、Pythonで対象企業の記事だけを抽出)
            if rec_url:
                rec_slug_match = re.search(r'companies/([^/]+)', rec_url)
                rec_slug = rec_slug_match.group(1) if rec_slug_match else ""
                
                # クエリはシンプルに
                q_hr = f"{company} インタビュー site:wantedly.com"
                raw_hr = client.search(query=q_hr, max_results=20).get("results", [])
                
                # Python側でURL構造をチェック
                filtered_hr = []
                for r in raw_hr:
                    # 企業のページ配下であること、またはpost_articles/storiesを含むこと
                    if rec_slug and rec_slug in r["url"]:
                        filtered_hr.append(r)
                    elif not rec_slug and ("post_articles" in r["url"] or "stories" in r["url"]):
                        filtered_hr.append(r)
                results["ヒト・組織"] = filtered_hr[:5]

            st.session_state.search_results = results
            st.session_state.search_done = True
            st.session_state.research_done = False # 再検索時はリセット
            st.rerun()
            
        except Exception as e:
            st.error(f"検索エラーが発生しました: {e}")
