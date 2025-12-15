import streamlit as st
import requests
import pandas as pd
import time

# --- 페이지 설정 ---
st.set_page_config(page_title="SoccerModel: Advanced Analyzer", page_icon="⚽", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #f0f2f6; }
    div.stButton > button { width: 100%; background-color: #ff4b4b; color: white; font-weight: bold; height: 50px; font-size: 20px; }
    .metric-card { background-color: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); text-align: center; }
    .info-box { background-color: #e8f4f8; padding: 15px; border-radius: 10px; margin-bottom: 20px; color: #005580; font-size: 0.9rem; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 🔑 API KEY (Streamlit Secrets)
# ==========================================
try:
    API_KEY = st.secrets["API_KEY"]
except:
    st.error("API 키를 찾을 수 없습니다. (Streamlit Secrets 설정 필요)")
    API_KEY = ""

BASE_URL = f"https://www.thesportsdb.com/api/v1/json/{API_KEY}"

# 1. 리그 목록 (Main Leagues)
LEAGUES = {
    "EPL (ENG)": "4328", "La Liga (ESP)": "4335", "Bundesliga (GER)": "4331",
    "Serie A (ITA)": "4332", "Ligue 1 (FRA)": "4334", "Eredivisie (NED)": "4337",
    "Primeira Liga (POR)": "4344", "Super Lig (TUR)": "4339", "K League 1 (KOR)": "4689",
    "J1 League (JPN)": "4633", "Saudi Pro League": "4668", "MLS (USA)": "4346"
}

# 2. 통합 분석을 위한 추가 대회 ID (Domestic Cup + International)
# 리그 선택 시 자동으로 함께 검색할 대회들입니다.
# (모든 컵을 다 넣으면 너무 느려지므로, 주요 대회 위주로 매핑합니다.)
DOMESTIC_CUPS = {
    "4328": ["4338", "4342"], # EPL -> FA Cup, League Cup
    "4335": ["4467"], # La Liga -> Copa del Rey
    "4331": ["4347"], # Bundesliga -> DFB Pokal
    "4332": ["4359"], # Serie A -> Coppa Italia
    "4334": ["4484"], # Ligue 1 -> Coupe de France
}

# 국제 대회 (모든 리그 공통 체크)
INTL_CUPS = ["4480", "4481", "4857"] # UCL, UEL, UECL

RANK_OPTIONS = {"리그 1위 (Leader)": 1, "리그 2위 (2nd Place)": 2}

# [수정됨] 3연속 무승(Winless) 추가
STREAK_OPTIONS = {
    "최근 1무 (Last: Draw)": ["D"],
    "최근 1패 (Last: Loss)": ["L"],
    "최근 1무 1패 (Draw -> Loss)": ["L", "D"], 
    "최근 1패 1무 (Loss -> Draw)": ["D", "L"],
    "최근 2패 (Loss -> Loss)": ["L", "L"],
    "최근 2무 (Draw -> Draw)": ["D", "D"],
    "⚠️ 최근 3경기 무승 (3 Winless)": "3_WINLESS"  # [New] 특별 코드
}

VENUE_OPTIONS = {
    "전체 (All Matches)": "All",
    "다음 경기가 홈일 때 (Next is Home)": "Home",
    "다음 경기가 원정일 때 (Next is Away)": "Away"
}

# --- 로직 함수 ---

def get_seasons(league_id, logs):
    """2019년 이후 시즌 목록 가져오기"""
    url = f"{BASE_URL}/search_all_seasons.php?id={league_id}"
    try:
        res = requests.get(url).json()
        if not res or 'seasons' not in res:
            logs.append("⚠️ 시즌 정보 없음")
            return []
        
        valid = []
        for s in res['seasons']:
            try:
                # 2019-2020 or 2019
                year_str = s['strSeason'].split('-')[0] if '-' in s['strSeason'] else s['strSeason']
                if int(year_str) >= 2019:
                    valid.append(s['strSeason'])
            except: continue
        return valid
    except Exception as e:
        logs.append(f"에러: {e}")
        return []

def get_events(league_id, season):
    """특정 리그/컵의 경기 데이터 가져오기"""
    try:
        url = f"{BASE_URL}/eventsseason.php?id={league_id}&s={season}"
        res = requests.get(url).json()
        return res['events'] if res and 'events' in res else []
    except: return []

def analyze(main_league_id, target_rank, streak_pattern, venue_filter, progress_bar, status_text, debug_area):
    logs = []
    seasons = get_seasons(main_league_id, logs)
    
    if not seasons:
        debug_area.code("\n".join(logs))
        return None
    
    stats = {"total": 0, "W": 0, "D": 0, "L": 0}
    total_seasons = len(seasons)
    
    # 함께 분석할 컵 대회 목록 구성
    target_cups = DOMESTIC_CUPS.get(main_league_id, []) + INTL_CUPS
    
    for i, season in enumerate(seasons):
        status_text.text(f"🔍 Season {season} 분석 중 (리그 + 컵대회 통합)...")
        progress_bar.progress((i + 1) / total_seasons)
        
        # 1. [데이터 수집] 리그 경기 + 컵 경기 모두 가져오기
        all_matches = []
        
        # (1) 리그 경기 (순위 산정용 + 기록용)
        league_events = get_events(main_league_id, season)
        for m in league_events:
            m['is_league'] = True # 리그 경기 표시
            all_matches.append(m)
            
        # (2) 컵/국제 경기 (기록용 Only)
        for cup_id in target_cups:
            cup_events = get_events(cup_id, season)
            for m in cup_events:
                m['is_league'] = False # 컵 경기 표시
                all_matches.append(m)
        
        if not all_matches: continue
        
        # 2. [데이터 정렬] 날짜순으로 전체 통합 정렬
        # 날짜가 없는 데이터 제외
        all_matches = [m for m in all_matches if m['dateEvent']]
        all_matches.sort(key=lambda x: x['dateEvent'])
        
        # 3. [시뮬레이션]
        threshold = 5 
        team_pts = {}  # 리그 승점 (리그 경기만 반영)
        team_hist = {} # 팀 흐름 (모든 경기 반영)
        
        for idx, m in enumerate(all_matches):
            if m['intHomeScore'] is None: continue
            
            h_team, a_team = m['strHomeTeam'], m['strAwayTeam']
            h_sc, a_sc = int(m['intHomeScore']), int(m['intAwayScore'])
            
            # 경기 결과 판별
            if h_sc > a_sc: h_res, a_res, h_p, a_p = 'W', 'L', 3, 0
            elif h_sc == a_sc: h_res, a_res, h_p, a_p = 'D', 'D', 1, 1
            else: h_res, a_res, h_p, a_p = 'L', 'W', 0, 3
            
            # 분석 시점: 일정 경기 수 이후
            if idx > threshold:
                # -------------------------------------------------
                # Step A. 순위 확인 (오직 리그 승점 team_pts 기준!)
                # -------------------------------------------------
                sorted_teams = sorted(team_pts.items(), key=lambda x: x[1], reverse=True)
                
                if len(sorted_teams) >= target_rank:
                    target_name = sorted_teams[target_rank-1][0]
                    
                    # 이번 경기에 타겟 팀이 있는가?
                    role = None
                    if h_team == target_name: role = 'Home'
                    elif a_team == target_name: role = 'Away'
                    
                    if role:
                        # -------------------------------------------------
                        # Step B. 흐름(Streak) 확인 (컵 포함된 team_hist 기준)
                        # -------------------------------------------------
                        hist = team_hist.get(target_name, [])
                        is_match = False
                        
                        # [조건] 3 Winless (특별 케이스)
                        if streak_pattern == "3_WINLESS":
                            if len(hist) >= 3:
                                # 최근 3경기가 모두 승리가 아님 (W가 없음)
                                last_3 = hist[-3:]
                                if "W" not in last_3:
                                    is_match = True
                        
                        # [조건] 일반 패턴 (리스트 비교)
                        elif isinstance(streak_pattern, list):
                            pat_len = len(streak_pattern)
                            if len(hist) >= pat_len:
                                check = True
                                for k in range(pat_len):
                                    # hist는 [...과거, 최근] 순서
                                    if hist[-(k+1)] != streak_pattern[k]:
                                        check = False; break
                                if check: is_match = True
                        
                        # -------------------------------------------------
                        # Step C. 예측 적중 확인
                        # -------------------------------------------------
                        if is_match:
                            # 홈/원정 필터 (이번 경기 기준)
                            if venue_filter == "All" or role == venue_filter:
                                stats["total"] += 1
                                my_result = h_res if role == 'Home' else a_res
                                stats[my_result] += 1

            # 4. [기록 업데이트]
            # 승점: 리그 경기일 때만 업데이트
            if m.get('is_league', False):
                team_pts[h_team] = team_pts.get(h_team, 0) + h_p
                team_pts[a_team] = team_pts.get(a_team, 0) + a_p
            
            # 흐름(Streak): 리그/컵 상관없이 무조건 업데이트
            if h_team not in team_hist: team_hist[h_team] = []
            if a_team not in team_hist: team_hist[a_team] = []
            team_hist[h_team].append(h_res)
            team_hist[a_team].append(a_res)
            
    debug_area.code("\n".join(logs))
    return stats

# --- UI ---
st.title("🏆 SoccerModel: Cross-Competition Analyzer")
st.markdown("""
<div class='info-box'>
    <b>💡 업그레이드 기능 적용됨:</b><br>
    1. <b>순위(Rank):</b> 선택한 리그의 순위표만 기준으로 산정합니다.<br>
    2. <b>흐름(Streak):</b> 리그 + 컵대회 + 국제대회(UCL 등)를 모두 포함하여 판별합니다.<br>
    3. <b>Winless:</b> '최근 3경기 무승' 옵션이 추가되었습니다.
</div>
""", unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns(4)
with c1: s_league = st.selectbox("1. 리그 (League)", list(LEAGUES.keys()))
with c2: s_rank = st.selectbox("2. 순위 (Rank)", list(RANK_OPTIONS.keys()))
with c3: s_streak = st.selectbox("3. 직전 기록 (Streak)", list(STREAK_OPTIONS.keys()))
with c4: s_venue = st.selectbox("4. 다음 경기 장소", list(VENUE_OPTIONS.keys()))

if st.button("🚀 통합 분석 실행 (Start Analysis)"):
    if not API_KEY:
        st.error("API 키가 설정되지 않았습니다.")
    else:
        prog = st.progress(0)
        stat = st.empty()
        debug = st.empty()
        
        # [데이터 전처리] 선택값 매핑
        streak_val = STREAK_OPTIONS[s_streak]
        venue_val = VENUE_OPTIONS[s_venue]
        
        res = analyze(LEAGUES[s_league], RANK_OPTIONS[s_rank], streak_val, venue_val, prog, stat, debug)
        prog.empty(); stat.empty()
        
        if res and res['total'] > 0:
            tot = res['total']
            st.success(f"✅ 분석 완료! 총 {tot}건의 사례 발견")
            c1, c2, c3 = st.columns(3)
            c1.metric("승리 확률 (Win)", f"{(res['W']/tot)*100:.1f}%", f"{res['W']}회")
            c2.metric("무승부 확률 (Draw)", f"{(res['D']/tot)*100:.1f}%", f"{res['D']}회")
            c3.metric("패배 확률 (Loss)", f"{(res['L']/tot)*100:.1f}%", f"{res['L']}회", delta_color="inverse")
        else:
            st.warning("조건에 맞는 데이터가 없습니다.")
