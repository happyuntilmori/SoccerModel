import streamlit as st
import requests
import pandas as pd
import time

# --- 페이지 설정 ---
st.set_page_config(page_title="SoccerModel: Match Logs", page_icon="⚽", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #f0f2f6; }
    div.stButton > button { width: 100%; background-color: #ff4b4b; color: white; font-weight: bold; height: 50px; font-size: 20px; }
    .info-box { background-color: #e8f4f8; padding: 15px; border-radius: 10px; margin-bottom: 20px; color: #005580; font-size: 0.9rem; }
    .match-row { background-color: white; padding: 10px; border-radius: 5px; margin-bottom: 8px; border-left: 5px solid #ddd; }
    .win { border-left-color: #4b89dc; }
    .loss { border-left-color: #dc4b4b; }
    .draw { border-left-color: #999; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 🔑 API KEY (Streamlit Secrets)
# ==========================================
try:
    API_KEY = st.secrets["API_KEY"]
except:
    st.error("🚨 API 키가 설정되지 않았습니다. Streamlit Secrets를 확인해주세요.")
    st.stop()

BASE_URL = f"https://www.thesportsdb.com/api/v1/json/{API_KEY}"

# 1. 리그 목록 (모든 리그 복원)
LEAGUES = {
    # 1부
    "EPL (ENG)": "4328", "La Liga (ESP)": "4335", "Bundesliga (GER)": "4331",
    "Serie A (ITA)": "4332", "Ligue 1 (FRA)": "4334", "Eredivisie (NED)": "4337",
    "Primeira Liga (POR)": "4344", "Super Lig (TUR)": "4339", 
    # 2부
    "Championship (ENG)": "4329", "La Liga 2 (ESP)": "4361", "2. Bundesliga (GER)": "4399",
    "Serie B (ITA)": "4394", "Ligue 2 (FRA)": "4401", "J2 League (JPN)": "4824",
    # 기타
    "K League 1 (KOR)": "4689", "J1 League (JPN)": "4633", 
    "Saudi Pro League": "4668", "MLS (USA)": "4346",
    "Russian Premier": "4355", "Superliga (DEN)": "4340", "Eliteserien (NOR)": "4358", 
    "Scottish Prem": "4330", "Brazil Serie A": "4351", "Primera Argentina": "4406", "Liga MX (MEX)": "4350"
}

# 2. 국내 컵대회 매핑
DOMESTIC_CUPS = {
    "4328": ["4338", "4342"], "4335": ["4467"], "4331": ["4347"], 
    "4332": ["4359"], "4334": ["4484"], "4337": ["4465"], 
    "4344": ["4466"], "4689": ["4690"], "4633": ["4828", "4637"], 
}

# 3. 국제 대항전 매핑
INTL_CUPS = ["4480", "4481", "4857", "4492"]

RANK_OPTIONS = {"리그 1위 (Leader)": 1, "리그 2위 (2nd Place)": 2}

STREAK_OPTIONS = {
    "최근 1무 (Last: Draw)": ["D"],
    "최근 1패 (Last: Loss)": ["L"],
    "최근 1무 1패 (Draw -> Loss)": ["L", "D"], 
    "최근 1패 1무 (Loss -> Draw)": ["D", "L"],
    "최근 2패 (Loss -> Loss)": ["L", "L"],
    "최근 2무 (Draw -> Draw)": ["D", "D"],
    "⚠️ 최근 3경기 무승 (3 Winless)": "3_WINLESS"
}

VENUE_OPTIONS = {
    "전체 (All Matches)": "All",
    "다음 경기가 홈일 때 (Next is Home)": "Home",
    "다음 경기가 원정일 때 (Next is Away)": "Away"
}

# --- 로직 함수 ---

def get_seasons(league_id, logs):
    url = f"{BASE_URL}/search_all_seasons.php?id={league_id}"
    try:
        res = requests.get(url)
        if res.status_code != 200: return []
        try: data = res.json()
        except: return []

        if not data or 'seasons' not in data: return []
        
        valid = []
        for s in data['seasons']:
            try:
                y_str = s['strSeason'].split('-')[0] if '-' in s['strSeason'] else s['strSeason']
                if int(y_str) >= 2019:
                    valid.append(s['strSeason'])
            except: continue
        return valid
    except: return []

def get_events(league_id, season):
    try:
        url = f"{BASE_URL}/eventsseason.php?id={league_id}&s={season}"
        res = requests.get(url)
        if res.status_code != 200: return []
        try: data = res.json()
        except: return []
        return data['events'] if data and 'events' in data else []
    except: return []

def analyze(main_league_id, target_rank, streak_pattern, venue_filter, progress_bar, status_text, debug_area):
    logs = []
    seasons = get_seasons(main_league_id, logs)
    
    if not seasons:
        debug_area.code("❌ 시즌 데이터를 불러오지 못했습니다. API 키 또는 리그 ID를 확인하세요.")
        return None, []
    
    stats = {"total": 0, "W": 0, "D": 0, "L": 0}
    match_logs = [] # [NEW] 상세 경기 기록 저장용 리스트
    
    total_seasons = len(seasons)
    target_cup_ids = DOMESTIC_CUPS.get(main_league_id, []) + INTL_CUPS
    
    for i, season in enumerate(seasons):
        status_text.text(f"🔍 {season} 시즌 분석 중...")
        progress_bar.progress((i + 1) / total_seasons)
        
        all_matches = []
        
        # 1. 리그 데이터
        league_data = get_events(main_league_id, season)
        for m in league_data:
            m['is_league'] = True
            all_matches.append(m)
            
        # 2. 컵 데이터
        for cup_id in target_cup_ids:
            cup_data = get_events(cup_id, season)
            if cup_data:
                for m in cup_data:
                    m['is_league'] = False
                    all_matches.append(m)
        
        if not all_matches: continue
        
        # 날짜순 정렬
        all_matches = [m for m in all_matches if m['dateEvent']]
        all_matches.sort(key=lambda x: x['dateEvent'])
        
        threshold = 5
        team_pts = {}
        team_hist = {}
        
        for idx, m in enumerate(all_matches):
            if m['intHomeScore'] is None: continue
            
            h_team, a_team = m['strHomeTeam'], m['strAwayTeam']
            h_sc, a_sc = int(m['intHomeScore']), int(m['intAwayScore'])
            
            if h_sc > a_sc: h_res, a_res, h_p, a_p = 'W', 'L', 3, 0
            elif h_sc == a_sc: h_res, a_res, h_p, a_p = 'D', 'D', 1, 1
            else: h_res, a_res, h_p, a_p = 'L', 'W', 0, 3
            
            if idx > threshold:
                # A. 순위 (리그 기준)
                sorted_teams = sorted(team_pts.items(), key=lambda x: x[1], reverse=True)
                if len(sorted_teams) >= target_rank:
                    target_name = sorted_teams[target_rank-1][0]
                    
                    role = None
                    if h_team == target_name: role = 'Home'
                    elif a_team == target_name: role = 'Away'
                    
                    if role:
                        # B. 흐름 (전체)
                        hist = team_hist.get(target_name, [])
                        is_match = False
                        
                        # Streak 판단
                        if streak_pattern == "3_WINLESS":
                            if len(hist) >= 3:
                                last_3 = hist[-3:]
                                if "W" not in last_3: is_match = True
                        elif isinstance(streak_pattern, list):
                            pat_len = len(streak_pattern)
                            if len(hist) >= pat_len:
                                check = True
                                for k in range(pat_len):
                                    if hist[-(k+1)] != streak_pattern[k]:
                                        check = False; break
                                if check: is_match = True
                        
                        # C. 결과 집계 및 로그 저장
                        if is_match:
                            if venue_filter == "All" or role == venue_filter:
                                stats["total"] += 1
                                
                                # 내 결과 확인
                                my_res = h_res if role == 'Home' else a_res
                                stats[my_res] += 1
                                
                                # [NEW] 로그 저장
                                score_str = f"{h_sc} : {a_sc}"
                                opponent = a_team if role == 'Home' else h_team
                                
                                # 색상 및 아이콘 결정
                                if my_res == 'W':
                                    badge = "🟦 W"
                                    css_class = "win"
                                elif my_res == 'L':
                                    badge = "🟥 L"
                                    css_class = "loss"
                                else:
                                    badge = "⬜ D"
                                    css_class = "draw"
                                
                                match_logs.append({
                                    "date": m['dateEvent'],
                                    "target": target_name,
                                    "opponent": opponent,
                                    "score": score_str,
                                    "result": my_res,
                                    "badge": badge,
                                    "season": season,
                                    "css": css_class,
                                    "home_away": role
                                })
            
            # 업데이트
            if m.get('is_league', False):
                team_pts[h_team] = team_pts.get(h_team, 0) + h_p
                team_pts[a_team] = team_pts.get(a_team, 0) + a_p
            
            if h_team not in team_hist: team_hist[h_team] = []
            if a_team not in team_hist: team_hist[a_team] = []
            team_hist[h_team].append(h_res)
            team_hist[a_team].append(a_res)
            
    return stats, match_logs

# --- UI ---
st.title("🏆 SoccerModel: Verification Mode")
st.markdown("""
<div class='info-box'>
    <b>🔍 데이터 검증 기능 탑재:</b><br>
    분석된 모든 경기 리스트를 아래에서 확인할 수 있습니다.<br>
    (승리: <span style='color:blue'><b>Blue W</b></span> / 패배: <span style='color:red'><b>Red L</b></span>)
</div>
""", unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns(4)
with c1: s_league = st.selectbox("1. 리그", list(LEAGUES.keys()))
with c2: s_rank = st.selectbox("2. 순위", list(RANK_OPTIONS.keys()))
with c3: s_streak = st.selectbox("3. 흐름", list(STREAK_OPTIONS.keys()))
with c4: s_venue = st.selectbox("4. 장소", list(VENUE_OPTIONS.keys()))

if st.button("🚀 분석 실행 (Start Analysis)"):
    prog = st.progress(0)
    stat = st.empty()
    debug = st.empty()
    
    streak_val = STREAK_OPTIONS[s_streak]
    venue_val = VENUE_OPTIONS[s_venue]
    
    # [수정] 결과와 로그를 함께 받음
    stats, logs = analyze(LEAGUES[s_league], RANK_OPTIONS[s_rank], streak_val, venue_val, prog, stat, debug)
    prog.empty(); stat.empty()
    
    if stats and stats['total'] > 0:
        tot = stats['total']
        st.success(f"✅ 분석 완료! 총 {tot}건의 사례 발견")
        
        # 1. 통계 요약
        c1, c2, c3 = st.columns(3)
        c1.metric("승리 (Win)", f"{(stats['W']/tot)*100:.1f}%", f"{stats['W']}회")
        c2.metric("무승부 (Draw)", f"{(stats['D']/tot)*100:.1f}%", f"{stats['D']}회")
        c3.metric("패배 (Loss)", f"{(stats['L']/tot)*100:.1f}%", f"{stats['L']}회", delta_color="inverse")
        
        st.divider()
        
        # 2. [NEW] 상세 경기 리스트 출력
        st.subheader(f"📋 상세 매치 리스트 ({tot}건)")
        
        # 최신순 정렬 (원하면 reverse=True)
        logs.sort(key=lambda x: x['date'], reverse=True)
        
        for log in logs:
            # HTML을 사용하여 커스텀 디자인 적용
            row_html = f"""
            <div class='match-row {log['css']}'>
                <div style='display: flex; justify-content: space-between; align-items: center;'>
                    <div>
                        <span style='font-size: 0.8em; color: #666;'>{log['date']} ({log['season']})</span><br>
                        <span style='font-weight: bold; font-size: 1.1em;'>{log['target']}</span> 
                        vs {log['opponent']}
                        <span style='font-size: 0.9em; color: #888;'>({log['home_away']})</span>
                    </div>
                    <div style='text-align: right;'>
                        <span style='font-weight: bold; font-size: 1.2em;'>{log['score']}</span><br>
                        <span style='font-weight: bold;'>{log['badge']}</span>
                    </div>
                </div>
            </div>
            """
            st.markdown(row_html, unsafe_allow_html=True)
            
    else:
        st.warning("조건에 맞는 데이터가 없습니다.")
