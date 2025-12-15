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
# 🔑 API KEY (Secrets)
# ==========================================
try:
    API_KEY = st.secrets["API_KEY"]
except:
    st.error("API 키 설정을 확인해주세요.")
    API_KEY = ""

BASE_URL = f"https://www.thesportsdb.com/api/v1/json/{API_KEY}"

# 1. 분석할 리그 목록
LEAGUES = {
    "EPL (ENG)": "4328", "La Liga (ESP)": "4335", "Bundesliga (GER)": "4331",
    "Serie A (ITA)": "4332", "Ligue 1 (FRA)": "4334", "Eredivisie (NED)": "4337",
    "Primeira Liga (POR)": "4344", "Super Lig (TUR)": "4339", 
    "K League 1 (KOR)": "4689", "J1 League (JPN)": "4633", 
    "Saudi Pro League": "4668", "MLS (USA)": "4346"
}

# 2. [자동 매핑] 리그별 국내 컵대회 ID (제가 미리 찾아두었습니다!)
DOMESTIC_CUPS = {
    "4328": ["4338", "4342"], # EPL -> FA Cup, League Cup
    "4335": ["4467"], # La Liga -> Copa del Rey
    "4331": ["4347"], # Bundesliga -> DFB Pokal
    "4332": ["4359"], # Serie A -> Coppa Italia
    "4334": ["4484"], # Ligue 1 -> Coupe de France
    "4337": ["4465"], # Eredivisie -> KNVB Cup
    "4344": ["4466"], # Portugal -> Taca de Portugal
    "4689": ["4690"], # K-League -> FA Cup (Korea Cup)
    "4633": ["4828", "4637"], # J-League -> Emperors Cup, J-League Cup
}

# 3. [자동 매핑] 국제 대항전 ID (챔스, 유로파, 아챔 등)
# 모든 팀에 대해 이 대회 기록이 있는지 찔러봅니다. (없으면 자동으로 무시됨)
INTL_CUPS = [
    "4480", # UEFA Champions League (UCL)
    "4481", # UEFA Europa League (UEL)
    "4857", # UEFA Conference League (UECL)
    "4492", # AFC Champions League (ACL) - 아시아 팀용
]

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
        res = requests.get(url).json()
        if not res or 'seasons' not in res: return []
        valid = []
        for s in res['seasons']:
            try:
                # 2019년 이후 시즌만 필터링
                y_str = s['strSeason'].split('-')[0] if '-' in s['strSeason'] else s['strSeason']
                if int(y_str) >= 2019:
                    valid.append(s['strSeason'])
            except: continue
        return valid
    except: return []

def get_events(league_id, season):
    """특정 대회의 경기 데이터 가져오기"""
    try:
        url = f"{BASE_URL}/eventsseason.php?id={league_id}&s={season}"
        res = requests.get(url).json()
        return res['events'] if res and 'events' in res else []
    except: return []

def analyze(main_league_id, target_rank, streak_pattern, venue_filter, progress_bar, status_text, debug_area):
    logs = []
    seasons = get_seasons(main_league_id, logs)
    
    if not seasons:
        debug_area.code("시즌 데이터를 불러오지 못했습니다.")
        return None
    
    stats = {"total": 0, "W": 0, "D": 0, "L": 0}
    total_seasons = len(seasons)
    
    # [설정] 분석할 컵 대회 ID 목록 합치기
    target_cup_ids = DOMESTIC_CUPS.get(main_league_id, []) + INTL_CUPS
    
    for i, season in enumerate(seasons):
        status_text.text(f"🔍 {season} 시즌 분석 중 (리그 + 컵 + 국제대회 통합)...")
        progress_bar.progress((i + 1) / total_seasons)
        
        all_matches = []
        
        # 1. 리그 데이터 (순위 산정용 + Streak용)
        league_data = get_events(main_league_id, season)
        for m in league_data:
            m['is_league'] = True # 리그 경기 표시
            all_matches.append(m)
            
        # 2. 컵 데이터 (Streak용 Only) - 없으면 그냥 넘어감
        for cup_id in target_cup_ids:
            cup_data = get_events(cup_id, season)
            if cup_data:
                for m in cup_data:
                    m['is_league'] = False # 컵 경기 표시
                    all_matches.append(m)
        
        if not all_matches: continue
        
        # 3. 날짜순 정렬 (통합 타임라인 생성)
        all_matches = [m for m in all_matches if m['dateEvent']]
        all_matches.sort(key=lambda x: x['dateEvent'])
        
        # 4. 시뮬레이션
        threshold = 5
        team_pts = {} # 리그 승점
        team_hist = {} # 통합 흐름 (Winless 판단용)
        
        for idx, m in enumerate(all_matches):
            if m['intHomeScore'] is None: continue
            
            h_team, a_team = m['strHomeTeam'], m['strAwayTeam']
            h_sc, a_sc = int(m['intHomeScore']), int(m['intAwayScore'])
            
            if h_sc > a_sc: h_res, a_res, h_p, a_p = 'W', 'L', 3, 0
            elif h_sc == a_sc: h_res, a_res, h_p, a_p = 'D', 'D', 1, 1
            else: h_res, a_res, h_p, a_p = 'L', 'W', 0, 3
            
            # 분석 시작
            if idx > threshold:
                # A. 순위 확인 (오직 리그 데이터만 사용)
                sorted_teams = sorted(team_pts.items(), key=lambda x: x[1], reverse=True)
                
                if len(sorted_teams) >= target_rank:
                    target_name = sorted_teams[target_rank-1][0]
                    
                    # 이번 경기에 타겟 팀 출전?
                    role = None
                    if h_team == target_name: role = 'Home'
                    elif a_team == target_name: role = 'Away'
                    
                    if role:
                        # B. 흐름 확인 (컵 포함 모든 데이터 사용)
                        hist = team_hist.get(target_name, [])
                        is_match = False
                        
                        # (1) 3 Winless 체크
                        if streak_pattern == "3_WINLESS":
                            if len(hist) >= 3:
                                last_3 = hist[-3:]
                                if "W" not in last_3: # 승리가 하나도 없으면
                                    is_match = True
                        
                        # (2) 일반 패턴 체크
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
            
            # 5. 데이터 업데이트
            # 승점: 리그 경기일 때만!
            if m.get('is_league', False):
                team_pts[h_team] = team_pts.get(h_team, 0) + h_p
                team_pts[a_team] = team_pts.get(a_team, 0) + a_p
            
            # 흐름: 리그+컵 모두!
            if h_team not in team_hist: team_hist[h_team] = []
            if a_team not in team_hist: team_hist[a_team] = []
            team_hist[h_team].append(h_res)
            team_hist[a_team].append(a_res)
            
    return stats

# --- UI ---
st.title("🏆 SoccerModel: Multi-Cup Analyzer")
st.markdown("""
<div class='info-box'>
    <b>ℹ️ 작동 원리:</b><br>
    • 리그를 선택하면 <b>FA컵, 챔피언스리그(UCL/ACL)</b> 등의 데이터를 자동으로 함께 수집합니다.<br>
    • <b>순위</b>는 '리그 승점'만으로 계산합니다.<br>
    • <b>Winless(무승) 흐름</b>은 '모든 컵대회'를 포함하여 현실적으로 판단합니다.
</div>
""", unsafe_allow_html
