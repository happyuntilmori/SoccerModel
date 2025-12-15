import streamlit as st
import requests
import pandas as pd
import time

# --- 페이지 설정 ---
st.set_page_config(page_title="SoccerModel: Win Streak Analyzer", page_icon="⚽", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #f0f2f6; }
    div.stButton > button { width: 100%; background-color: #ff4b4b; color: white; font-weight: bold; height: 50px; font-size: 20px; }
    .metric-card { background-color: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); text-align: center; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 🔑 API KEY 설정 (Streamlit Secrets 사용)
# ==========================================
try:
    API_KEY = st.secrets["API_KEY"]
except:
    # 로컬 테스트용 (배포 시에는 Secrets가 작동함)
    st.error("API 키를 찾을 수 없습니다. Streamlit Secrets를 설정해주세요.")
    API_KEY = ""

BASE_URL = f"https://www.thesportsdb.com/api/v1/json/{API_KEY}"

# 리그 목록
LEAGUES = {
    "EPL (ENG)": "4328", "La Liga (ESP)": "4335", "Bundesliga (GER)": "4331",
    "Serie A (ITA)": "4332", "Ligue 1 (FRA)": "4334", "Eredivisie (NED)": "4337",
    "Primeira Liga (POR)": "4344", "Super Lig (TUR)": "4339", "Russian Premier": "4355",
    "Superliga (DEN)": "4340", "Eliteserien (NOR)": "4358", "Scottish Prem": "4330",
    "Championship (ENG)": "4329", "La Liga 2 (ESP)": "4361", "2. Bundesliga (GER)": "4399",
    "Serie B (ITA)": "4394", "Ligue 2 (FRA)": "4401", "UCL (Champions)": "4480",
    "UEL (Europa)": "4481", "UECL (Conf)": "4857", "K League 1 (KOR)": "4689",
    "J1 League (JPN)": "4633", "J2 League (JPN)": "4824", "Saudi Pro League": "4668",
    "Indian Super League": "4791", "A-League (AUS)": "4356", "Brazil Serie A": "4351",
    "Primera Argentina": "4406", "MLS (USA)": "4346", "Liga MX (MEX)": "4350",
    "Concacaf Nations": "4866"
}

RANK_OPTIONS = {"리그 1위 (Leader)": 1, "리그 2위 (2nd Place)": 2}

STREAK_OPTIONS = {
    "최근 1무 (Last: Draw)": ["D"],
    "최근 1패 (Last: Loss)": ["L"],
    "최근 1무 1패 (Draw -> Loss)": ["L", "D"], 
    "최근 1패 1무 (Loss -> Draw)": ["D", "L"],
    "최근 2패 (Loss -> Loss)": ["L", "L"],
    "최근 2무 (Draw -> Draw)": ["D", "D"]
}

VENUE_OPTIONS = {
    "전체 (All Matches)": "All",
    "다음 경기가 홈일 때 (Next is Home)": "Home",
    "다음 경기가 원정일 때 (Next is Away)": "Away"
}

# --- 로직 함수 ---

def get_seasons(league_id):
    url = f"{BASE_URL}/search_all_seasons.php?id={league_id}"
    try:
        res = requests.get(url)
        if res.status_code != 200: return []
        data = res.json()
        if not data or 'seasons' not in data: return []
        
        valid = []
        for s in data['seasons']:
            try:
                if int(s['strSeason'][:4]) >= 2019:
                    valid.append(s['strSeason'])
            except: continue
        return valid
    except: return []

def get_matches(league_id, season):
    try:
        url = f"{BASE_URL}/eventsseason.php?id={league_id}&s={season}"
        res = requests.get(url).json()
        return res['events'] if res and 'events' in res else []
    except: return []

def analyze(league_id, target_rank, streak_pattern, venue_filter, progress_bar, status_text):
    seasons = get_seasons(league_id)
    if not seasons: return None
    
    stats = {"total": 0, "W": 0, "D": 0, "L": 0}
    total_seasons = len(seasons)
    
    for i, season in enumerate(seasons):
        status_text.text(f"🔍 Season {season} 분석 중 ({i+1}/{total_seasons})...")
        progress_bar.progress((i + 1) / total_seasons)
        
        matches = get_matches(league_id, season)
        if not matches: continue
        
        matches = [m for m in matches if m['dateEvent']]
        matches.sort(key=lambda x: x['dateEvent'])
        threshold = 5 
        
        team_pts = {}
        team_hist = {} # 홈/원정 구분 없는 전체 기록
        
        for idx, m in enumerate(matches):
            if m['intHomeScore'] is None: continue
            h_team, a_team = m['strHomeTeam'], m['strAwayTeam']
            h_sc, a_sc = int(m['intHomeScore']), int(m['intAwayScore'])
            
            # 결과 판별
            if h_sc > a_sc: h_res, a_res, h_p, a_p = 'W', 'L', 3, 0
            elif h_sc == a_sc: h_res, a_res, h_p, a_p = 'D', 'D', 1, 1
            else: h_res, a_res, h_p, a_p = 'L', 'W', 0, 3
            
            # 5경기 이후부터 분석
            if idx > threshold:
                sorted_teams = sorted(team_pts.items(), key=lambda x: x[1], reverse=True)
                if len(sorted_teams) >= target_rank:
                    target_name = sorted_teams[target_rank-1][0]
                    
                    # 이번 경기의 역할 (Home or Away)
                    role = None
                    if h_team == target_name: role = 'Home'
                    elif a_team == target_name: role = 'Away'
                    
                    if role:
                        # 1. 과거 기록(Streak) 확인 (장소 무관)
                        hist = team_hist.get(target_name, [])
                        pat_len = len(streak_pattern)
                        
                        if len(hist) >= pat_len:
                            # 패턴 매칭
                            is_match = True
                            for k in range(pat_len):
                                if hist[-(k+1)] != streak_pattern[k]:
                                    is_match = False; break
                            
                            # 패턴 일치 시 -> 이번 경기(Next Match) 필터링
                            if is_match:
                                if venue_filter == "All" or role == venue_filter:
                                    stats["total"] += 1
                                    my_result = h_res if role == 'Home' else a_res
                                    stats[my_result] += 1

            # 데이터 축적
            team_pts[h_team] = team_pts.get(h_team, 0) + h_p
            team_pts[a_team] = team_pts.get(a_team, 0) + a_p
            if h_team not in team_hist: team_hist[h_team] = []
            if a_team not in team_hist: team_hist[a_team] = []
            team_hist[h_team].append(h_res)
            team_hist[a_team].append(a_res)
            
    return stats

# --- UI ---
st.title("📉 SoccerModel: Win Streak Analyzer")
st.markdown("데이터 범위: **2019 ~ 현재** | **Streak(전체) → Next Match(홈/원정) 확률 분석**")

c1, c2, c3, c4 = st.columns(4)
with c1: s_league = st.selectbox("1. 리그", list(LEAGUES.keys()))
with c2: s_rank = st.selectbox("2. 순위", list(RANK_OPTIONS.keys()))
with c3: s_streak = st.selectbox("3. 직전 기록 (Streak)", list(STREAK_OPTIONS.keys()))
with c4: s_venue = st.selectbox("4. 다음 경기 장소", list(VENUE_OPTIONS.keys()))

st.divider()

if st.button("🚀 분석 실행 (Start Analysis)"):
    if not API_KEY:
        st.error("🚨 API 키가 설정되지 않았습니다. Streamlit Secrets를 확인하세요.")
    else:
        prog = st.progress(0)
        stat = st.empty()
        
        res = analyze(LEAGUES[s_league], RANK_OPTIONS[s_rank], STREAK_OPTIONS[s_streak], VENUE_OPTIONS[s_venue], prog, stat)
        prog.empty(); stat.empty()
        
        if res and res['total'] > 0:
            tot = res['total']
            st.success(f"✅ 분석 완료! 총 {tot}건의 사례 발견")
            c1, c2, c3 = st.columns(3)
            c1.metric("승리 확률 (Win)", f"{(res['W']/tot)*100:.1f}%", f"{res['W']}회")
            c2.metric("무승부 확률 (Draw)", f"{(res['D']/tot)*100:.1f}%", f"{res['D']}회")
            c3.metric("패배 확률 (Loss)", f"{(res['L']/tot)*100:.1f}%", f"{res['L']}회", delta_color="inverse")
        else:
            st.warning("조건에 맞는 데이터가 없습니다. (API 연결 상태나 검색 조건을 확인하세요)")
