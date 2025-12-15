import streamlit as st
import requests
import pandas as pd
import time

# --- 페이지 설정 ---
st.set_page_config(page_title="SoccerModel: Multi-Cup Analyzer", page_icon="🏆", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #f0f2f6; }
    div.stButton > button { width: 100%; background-color: #ff4b4b; color: white; font-weight: bold; height: 50px; font-size: 20px; }
    .info-box { background-color: #e8f4f8; padding: 15px; border-radius: 10px; margin-bottom: 20px; color: #005580; font-size: 0.9rem; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 🔑 API KEY (안전장치 포함)
# ==========================================
try:
    API_KEY = st.secrets["API_KEY"]
except:
    st.error("🚨 API 키가 설정되지 않았습니다. Streamlit Secrets를 확인해주세요.")
    st.stop()

BASE_URL = f"https://www.thesportsdb.com/api/v1/json/{API_KEY}"

# 1. 리그 목록
LEAGUES = {
    "EPL (ENG)": "4328", "La Liga (ESP)": "4335", "Bundesliga (GER)": "4331",
    "Serie A (ITA)": "4332", "Ligue 1 (FRA)": "4334", "Eredivisie (NED)": "4337",
    "Primeira Liga (POR)": "4344", "Super Lig (TUR)": "4339", 
    "K League 1 (KOR)": "4689", "J1 League (JPN)": "4633", 
    "Saudi Pro League": "4668", "MLS (USA)": "4346"
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

# --- 핵심 함수 (에러 방지 강화됨) ---

def get_seasons(league_id, logs):
    """시즌 목록 가져오기"""
    url = f"{BASE_URL}/search_all_seasons.php?id={league_id}"
    try:
        res = requests.get(url)
        # 응답이 비어있거나 200 OK가 아니면 빈 리스트 반환
        if res.status_code != 200: return []
        try:
            data = res.json()
        except: return [] # JSON 변환 실패 시 무시

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
    """
    [핵심 수정] 
    컵대회 데이터가 없거나 깨져있을 때 에러를 내지 않고
    빈 리스트([])를 반환하도록 'try-except'를 2중으로 감쌌습니다.
    """
    try:
        url = f"{BASE_URL}/eventsseason.php?id={league_id}&s={season}"
        res = requests.get(url)
        
        if res.status_code != 200: return [] # 서버 에러면 통과
        
        try:
            data = res.json() # 여기서 에러가 많이 납니다 (Expecting value...)
        except:
            return [] # JSON이 아니면 그냥 빈 리스트 반환하고 끝냄 (앱 안 죽음)
            
        return data['events'] if data and 'events' in data else []
    except: return [] # 그 외 모든 에러 무시

def analyze(main_league_id, target_rank, streak_pattern, venue_filter, progress_bar, status_text, debug_area):
    logs = []
    seasons = get_seasons(main_league_id, logs)
    
    if not seasons:
        # 시즌조차 못 가져오면 이건 API 키 문제일 확률이 높음
        debug_area.error("데이터를 가져올 수 없습니다. API 키가 올바른지 확인해주세요.")
        return None
    
    stats = {"total": 0, "W": 0, "D": 0, "L": 0}
    total_seasons = len(seasons)
    
    target_cup_ids = DOMESTIC_CUPS.get(main_league_id, []) + INTL_CUPS
    
    for i, season in enumerate(seasons):
        status_text.text(f"🔍 {season} 시즌 분석 중...")
        progress_bar.progress((i + 1) / total_seasons)
        
        all_matches = []
        
        # 1. 리그 데이터 가져오기
        league_data = get_events(main_league_id, season)
        for m in league_data:
            m['is_league'] = True
            all_matches.append(m)
            
        # 2. 컵 데이터 가져오기 (에러나면 건너뜀)
        for cup_id in target_cup_ids:
            cup_data = get_events(cup_id, season)
            if cup_data: # 데이터가 있을 때만 추가
                for m in cup_data:
                    m['is_league'] = False
                    all_matches.append(m)
        
        if not all_matches: continue
        
        # 3. 날짜순 정렬
        all_matches = [m for m in all_matches if m['dateEvent']]
        all_matches.sort(key=lambda x: x['dateEvent'])
        
        # 4. 시뮬레이션
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
                # A. 순위 확인 (리그만)
                sorted_teams = sorted(team_pts.items(), key=lambda x: x[1], reverse=True)
                if len(sorted_teams) >= target_rank:
                    target_name = sorted_teams[target_rank-1][0]
                    
                    role = None
                    if h_team == target_name: role = 'Home'
                    elif a_team == target_name: role = 'Away'
                    
                    if role:
                        # B. 흐름 확인 (전체)
                        hist = team_hist.get(target_name, [])
                        is_match = False
                        
                        # 3 Winless
                        if streak_pattern == "3_WINLESS":
                            if len(hist) >= 3:
                                last_3 = hist[-3:]
                                if "W" not in last_3: is_match = True
                        # 일반 패턴
                        elif isinstance(streak_pattern, list):
                            pat_len = len(streak_pattern)
                            if len(hist) >= pat_len:
                                check = True
                                for k in range(pat_len):
                                    if hist[-(k+1)] != streak_pattern[k]:
                                        check = False; break
                                if check: is_match = True
                        
                        # C. 결과 집계
                        if is_match:
                            if venue_filter == "All" or role == venue_filter:
                                stats["total"] += 1
                                my_res = h_res if role == 'Home' else a_res
                                stats[my_res] += 1
            
            # 업데이트
            if m.get('is_league', False):
                team_pts[h_team] = team_pts.get(h_team, 0) + h_p
                team_pts[a_team] = team_pts.get(a_team, 0) + a_p
            
            if h_team not in team_hist: team_hist[h_team] = []
            if a_team not in team_hist: team_hist[a_team] = []
            team_hist[h_team].append(h_res)
            team_hist[a_team].append(a_res)
            
    return stats

# --- UI ---
st.title("🏆 SoccerModel: Robust Analyzer")
st.markdown("""
<div class='info-box'>
    <b>🛡️ 에러 방지 모드 적용됨:</b><br>
    데이터가 없는 컵대회나 시즌은 자동으로 건너뛰어 프로그램이 멈추지 않습니다.
</div>
""", unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns(4)
with c1: s_league = st.selectbox("1. 리그", list(LEAGUES.keys()))
with c2: s_rank = st.selectbox("2. 순위", list(RANK_OPTIONS.keys()))
with c3: s_streak = st.selectbox("3. 흐름", list(STREAK_OPTIONS.keys()))
with c4: s_venue = st.selectbox("4. 장소", list(VENUE_OPTIONS.keys()))

if st.button("🚀 분석 실행"):
    prog = st.progress(0)
    stat = st.empty()
    debug = st.empty()
    
    streak_val = STREAK_OPTIONS[s_streak]
    venue_val = VENUE_OPTIONS[s_venue]
    
    res = analyze(LEAGUES[s_league], RANK_OPTIONS[s_rank], streak_val, venue_val, prog, stat, debug)
    prog.empty(); stat.empty()
    
    if res and res['total'] > 0:
        tot = res['total']
        st.success(f"✅ 분석 완료! 총 {tot}건 발견")
        c1, c2, c3 = st.columns(3)
        c1.metric("승리 확률", f"{(res['W']/tot)*100:.1f}%", f"{res['W']}회")
        c2.metric("무승부 확률", f"{(res['D']/tot)*100:.1f}%", f"{res['D']}회")
        c3.metric("패배 확률", f"{(res['L']/tot)*100:.1f}%", f"{res['L']}회", delta_color="inverse")
    else:
        st.warning("조건에 맞는 데이터가 없습니다. (데이터 부족 또는 API 키 확인 필요)")
