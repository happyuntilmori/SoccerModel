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
# 🔑 API KEY (Streamlit Secrets)
# ==========================================
try:
    API_KEY = st.secrets["API_KEY"]
except:
    st.error("🚨 API 키가 설정되지 않았습니다. Streamlit Secrets를 확인해주세요.")
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

# 2. [자동 매핑] 리그별 국내 컵대회 ID (미리 찾아두었습니다!)
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
INTL_CUPS = [
    "4480", # UEFA Champions League (UCL)
    "4481", # UEFA Europa League (UEL)
    "4857", # UEFA Conference League (UECL)
    "4492", # AFC Champions League (ACL) - 아시아 팀용
]

RANK_OPTIONS = {"리그 1위 (Leader)": 1, "리그 2위 (2nd Place)": 2}

# [기능 추가] 3연속 무승 옵션
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
        if res.status_code != 200:
            logs.append(f"❌ API 연결 오류 (Status: {res.status_code})")
            return []
        data = res.json()
        if not data or 'seasons' not in data: return []
        
        valid = []
        for s in data['seasons']:
            try:
                # 2019년 이후 필터링
                y_str = s['strSeason'].split('-')[0] if '-' in s['strSeason'] else s['strSeason']
                if int(y_str) >= 2019:
                    valid.append(s['strSeason'])
            except: continue
        return valid
    except Exception as e:
        logs.append(f"⚠️ 시즌 조회 중 에러: {e}")
        return []

def get_events(league_id, season):
    """특정 대회의 경기 데이터 가져오기 (에러 방지 적용)"""
    try:
        url = f"{BASE_URL}/eventsseason.php?id={league_id}&s={season}"
        res = requests.get(url)
        if res.status_code != 200: return []
        data = res.json()
        return data['events'] if data and 'events' in data else []
    except: return []

def analyze(main_league_id, target_rank, streak_pattern, venue_filter, progress_bar, status_text, debug_area):
    logs = []
    seasons = get_seasons(main_league_id, logs)
    
    if not seasons:
        debug_area.code("❌ 시즌 데이터를 불러오지 못했습니다. API 키나 네트워크 상태를 확인하세요.\n" + "\n".join(logs))
        return None
    
    stats = {"total": 0, "W": 0, "D": 0, "L": 0}
    total_seasons = len(seasons)
    
    # [설정] 분석할 컵 대회 ID 목록 합치기 (리그별 컵 + 국제대회)
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
        team_pts = {} # 리그 승점 (순위용)
        team_hist = {} # 통합 흐름 (Streak용)
        
        for idx, m in enumerate(all_matches):
            if m['intHomeScore'] is None: continue
            
            h_team, a_team = m['strHomeTeam'], m['strAwayTeam']
            h_sc, a_sc = int(m['intHomeScore']), int(m['intAwayScore'])
            
            # 경기 결과 판별 (승/무/패)
            if h_sc > a_sc: h_res, a_res, h_p, a_p = 'W', 'L', 3, 0
            elif h_sc == a_sc: h_res, a_res, h_p, a_p = 'D', 'D', 1, 1
            else: h_res, a_res, h_p, a_p = 'L', 'W', 0, 3
            
            # 분석 시작 (시즌 초반 제외)
            if idx > threshold:
                # -----------------------------------------------
                # A. 순위 확인 (오직 리그 데이터(team_pts)만 사용)
                # -----------------------------------------------
                sorted_teams = sorted(team_pts.items(), key=lambda x: x[1], reverse=True)
                
                if len(sorted_teams) >= target_rank:
                    target_name = sorted_teams[target_rank-1][0]
                    
                    # 이번 경기에 타겟 팀이 출전하는가?
                    role = None
                    if h_team == target_name: role = 'Home'
                    elif a_team == target_name: role = 'Away'
                    
                    if role:
                        # -----------------------------------------------
                        # B. 흐름 확인 (컵 포함 모든 데이터(team_hist) 사용)
                        # -----------------------------------------------
                        hist = team_hist.get(target_name, [])
                        is_match = False
                        
                        # [기능 1] 3 Winless 체크 (최근 3경기 승리 없음)
                        if streak_pattern == "3_WINLESS":
                            if len(hist) >= 3:
                                last_3 = hist[-3:]
                                if "W" not in last_3: # 최근 3경기에 'W'가 하나도 없으면 조건 충족
                                    is_match = True
                        
                        # [기능 2] 일반 패턴 체크 (예: 패-무)
                        elif isinstance(streak_pattern, list):
                            pat_len = len(streak_pattern)
                            if len(hist) >= pat_len:
                                check = True
                                for k in range(pat_len):
                                    if hist[-(k+1)] != streak_pattern[k]:
                                        check = False; break
                                if check: is_match = True
                        
                        # C. 결과 집계 (다음 경기)
                        if is_match:
                            if venue_filter == "All" or role == venue_filter:
                                stats["total"] += 1
                                my_res = h_res if role == 'Home' else a_res
                                stats[my_res] += 1
            
            # 5. 데이터 업데이트
            # 승점: 리그 경기일 때만 업데이트 (Ezy님의 요청 엄수!)
            if m.get('is_league', False):
                team_pts[h_team] = team_pts.get(h_team, 0) + h_p
                team_pts[a_team] = team_pts.get(a_team, 0) + a_p
            
            # 흐름(Streak): 리그+컵 모두 업데이트 (승패 기록은 다 남김)
            if h_team not in team_hist: team_hist[h_team] = []
            if a_team not in team_hist: team_hist[a_team] = []
            team_hist[h_team].append(h_res)
            team_hist[a_team].append(a_res)
            
    return stats

# --- UI ---
st.title("🏆 SoccerModel: Multi-Cup Analyzer")
st.markdown("""
<div class='info-box'>
    <b>ℹ️ 업그레이드 완료:</b><br>
    • <b>순위(Rank):</b> 리그 승점만으로 엄격하게 계산합니다.<br>
    • <b>흐름(Streak):</b> 챔스, 유로파, FA컵 등 모든 공식 대회를 포함합니다.<br>
    • <b>3 Winless:</b> '최근 3경기 무승' 시 다음 경기 승률을 분석합니다.
</div>
""", unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns(4)
with c1: s_league = st.selectbox("1. 리그 (League)", list(LEAGUES.keys()))
with c2: s_rank = st.selectbox("2. 순위 (Rank)", list(RANK_OPTIONS.keys()))
with c3: s_streak = st.selectbox("3. 흐름 (Streak)", list(STREAK_OPTIONS.keys()))
with c4: s_venue = st.selectbox("4. 다음 경기 장소", list(VENUE_OPTIONS.keys()))

if st.button("🚀 통합 분석 실행 (Start Analysis)"):
    if not API_KEY:
        st.error("🚨 API 키가 없습니다. Streamlit Secrets 설정을 확인하세요.")
    else:
        prog =
