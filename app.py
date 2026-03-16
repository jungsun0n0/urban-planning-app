import streamlit as st
import requests
import geopandas as gpd
import pandas as pd
import warnings
import time
from io import BytesIO
import matplotlib.pyplot as plt
import matplotlib.patheffects as patheffects
import platform
import os
import PyPDF2
from dotenv import load_dotenv # ★ 금고 여는 라이브러리 추가
import math
import matplotlib.font_manager as fm
import tempfile
import zipfile
import json
import traceback

warnings.filterwarnings('ignore')

# ★ 금고(.env) 파일 열기
load_dotenv()

st.set_page_config(page_title="중심지 체계 현황 진단 시스템", page_icon="🏙️", layout="wide")

import urllib.request
import urllib.error

# ===== 가장 확실한 폰트 로드 방식 (로컬 파일 최우선) =====
custom_font_path = 'NanumGothic.ttf'
# 1. 로컬에 폰트가 없으면 다운로드 시도
if not os.path.exists(custom_font_path):
    try:
        urllib.request.urlretrieve("https://github.com/naver/nanumfont/raw/master/NanumFont_TTF_ALL/NanumGothic.ttf", custom_font_path)
    except Exception:
        pass

# 2. 폰트 적용
if os.path.exists(custom_font_path):
    try:
        fm.fontManager.addfont(custom_font_path)
        plt.rcParams['font.family'] = 'NanumGothic'
        custom_fontprops = fm.FontProperties(fname=custom_font_path)
    except Exception:
        plt.rcParams['font.family'] = 'Malgun Gothic' if platform.system() == 'Windows' else 'AppleGothic'
        custom_fontprops = fm.FontProperties(family=plt.rcParams['font.family'])
else:
    # 윈도우 기본 폰트 시도
    windows_font = 'C:/Windows/Fonts/malgun.ttf'
    if platform.system() == 'Windows' and os.path.exists(windows_font):
        try:
            fm.fontManager.addfont(windows_font)
            plt.rcParams['font.family'] = 'Malgun Gothic'
            custom_fontprops = fm.FontProperties(fname=windows_font)
        except Exception:
            plt.rcParams['font.family'] = 'Malgun Gothic'
            custom_fontprops = fm.FontProperties(family='Malgun Gothic')
    else:
        plt.rcParams['font.family'] = 'Malgun Gothic' if platform.system() == 'Windows' else 'AppleGothic'
        custom_fontprops = fm.FontProperties(family=plt.rcParams['font.family'])

plt.rcParams['axes.unicode_minus'] = False
# ==========================================================
# [설정] 환경변수에서 API 키 안전하게 불러오기! (코드에 키 노출 X)
# ==========================================================
VWORLD_KEY = os.getenv("VWORLD_KEY")
SGIS_KEY = os.getenv("SGIS_KEY")
SGIS_SECRET = os.getenv("SGIS_SECRET")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# ==========================================================

# ==========================================
# ★ 0-1. 지정된 폴더 안의 문서(PDF, TXT) 읽어오는 함수 추가
# ==========================================
def read_folder_documents(folder_name):
    text_content = ""
    # 폴더가 없으면 빈 텍스트 반환
    if not os.path.exists(folder_name):
        return ""
    
    TEXT_LIMIT = 100000
    
    for root, dirs, files in os.walk(folder_name):
        for file in files:
            if len(text_content) > TEXT_LIMIT:
                break
            
            file_path = os.path.join(root, file)
            # PDF 파일 읽기
            if file.lower().endswith('.pdf'):
                try:
                    with open(file_path, 'rb') as f:
                        reader = PyPDF2.PdfReader(f)
                        for page in reader.pages:
                            if len(text_content) > TEXT_LIMIT:
                                break
                            extracted = page.extract_text()
                            if extracted:
                                text_content += extracted + "\n"
                except Exception as e:
                    pass
            # TXT 파일 읽기
            elif file.lower().endswith('.txt'):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        text_content += f.read() + "\n"
                except Exception:
                    pass
    return text_content[:TEXT_LIMIT]

def extract_text_from_upload_cached(uploaded_files, state_key):
    if not uploaded_files:
        if state_key in st.session_state:
            st.session_state[state_key] = ""
        if f"{state_key}_files" in st.session_state:
            st.session_state[f"{state_key}_files"] = []
        return ""
    
    current_file_info = [(f.name, f.size) for f in uploaded_files]
    
    if state_key in st.session_state and f"{state_key}_files" in st.session_state:
        if st.session_state[f"{state_key}_files"] == current_file_info:
            return st.session_state[state_key]
            
    with st.spinner('문서를 분석하기 위해 텍스트를 추출 중입니다...'):
        TEXT_LIMIT = 100000
        text_content = ""
        for file in uploaded_files:
            if len(text_content) > TEXT_LIMIT:
                break
            
            file.seek(0)
            if file.name.lower().endswith('.pdf'):
                try:
                    reader = PyPDF2.PdfReader(file)
                    for page in reader.pages:
                        if len(text_content) > TEXT_LIMIT:
                            break
                        extracted = page.extract_text()
                        if extracted:
                            text_content += extracted + "\n"
                except Exception:
                    pass
            elif file.name.lower().endswith('.txt'):
                try:
                    text_content += file.getvalue().decode('utf-8') + "\n"
                except Exception:
                    pass
        
        text_content = text_content[:TEXT_LIMIT]
        st.session_state[state_key] = text_content
        st.session_state[f"{state_key}_files"] = current_file_info
        
    return text_content

# ==========================================
# ★ 0-2. 업로드된 공간자료(SHP/GeoJSON) 파싱 함수
# ==========================================
@st.cache_data(show_spinner=False)
def parse_uploaded_spatial_files(_uploaded_files):
    if not _uploaded_files:
        return None
    try:
        temp_dir = tempfile.mkdtemp()
        target_read_file = None
        for uf in _uploaded_files:
            file_path = os.path.join(temp_dir, uf.name)
            with open(file_path, "wb") as f:
                f.write(uf.getbuffer())
            if uf.name.lower().endswith('.shp') or uf.name.lower().endswith('.geojson') or uf.name.lower().endswith('.json'):
                target_read_file = file_path
                
        if target_read_file:
            gdf = gpd.read_file(target_read_file)
            return gdf
    except Exception:
        pass
    return None

with st.sidebar:
    st.markdown("### 🔗 참고 링크")
    st.info("[도시·군기본계획 통합열람 (토지이음)](https://www.eum.go.kr/web/in/pd/pdBoardList.jsp?subType=C&searchType=&searchWord=)")
    st.markdown("---")
    
    st.markdown("### 📁 B단계 참고 자료 업로드")
    
    # 텍스트 추출 한도 (예: 10만 자)
    TEXT_LIMIT = 100000
    
    st.markdown("**1. 상위계획**")
    uploaded_plan_files = st.file_uploader("상위계획 문서 업로드 (PDF, TXT)", type=['pdf', 'txt'], accept_multiple_files=True, key="upload_plan")
    
    if uploaded_plan_files:
        plan_extracted = extract_text_from_upload_cached(uploaded_plan_files, "plan_text_cache")
        if len(plan_extracted) > TEXT_LIMIT:
            st.warning('문서 용량이 너무 큽니다. 핵심 부분만 발췌해서 올려주세요')
    
    st.markdown("**2. 인접지자체 도시·군기본계획**")
    uploaded_adj_files = st.file_uploader("인접지자체 계획 문서 업로드 (PDF, TXT)", type=['pdf', 'txt'], accept_multiple_files=True, key="upload_adj")
    
    if uploaded_adj_files:
        adj_extracted = extract_text_from_upload_cached(uploaded_adj_files, "adj_text_cache")
        if len(adj_extracted) > TEXT_LIMIT:
             st.warning('문서 용량이 너무 큽니다. 핵심 부분만 발췌해서 올려주세요')
             
    st.markdown("**3. 지역현안사항 (공간 데이터 업로드)**")
    uploaded_spatial_files = st.file_uploader(
        "공간 데이터 업로드 (.geojson, .json 지정 또는 .shp, .shx, .dbf 파일들을 함께 선택)", 
        type=['geojson', 'json', 'shp', 'shx', 'dbf', 'prj'], 
        accept_multiple_files=True, 
        key="upload_spatial"
    )
    
    # SHP 파일 등은 묶음으로 처리하기 위한 임시 저장 로직
    spatial_data_status = st.empty()
    if uploaded_spatial_files:
        spatial_data_status.success(f"{len(uploaded_spatial_files)}개의 공간 파일이 업로드되었습니다. B단계 분석 시 행정동과 자동 교차 분석됩니다.")
            
    st.markdown("---")

# (이 아래부터는 기존의 SIDO_MAP 등 원래 코드가 그대로 이어지면 됩니다!)

SIDO_MAP = {
    "서울특별시": "11", "부산광역시": "21", "대구광역시": "22", "인천광역시": "23",
    "광주광역시": "24", "대전광역시": "25", "울산광역시": "26", "세종특별자치시": "29",
    "경기도": "31", "강원특별자치도": "32", "충청북도": "33", "충청남도": "34",
    "전북특별자치도": "35", "전라남도": "36", "경상북도": "37", "경상남도": "38",
    "제주특별자치도": "39"
}

MAP_COLORS = {
    "인구(명)_정규화": ("YlOrBr", "인구 수 (노란색 계통)"),
    "사업체(수)_정규화": ("Blues", "사업체 수 (파란색 계통)"),
    "종사자(수)_정규화": ("Purples", "종사자 수 (보라색 계통)"),
    "중심상업(%)_정규화": ("Reds", "중심상업지역 (빨간색 계통)"),
    "일반상업(%)_정규화": ("RdPu", "일반상업지역 (분홍색 계통)"),
    "근린상업(%)_정규화": ("PuRd", "근린상업지역 (자주색 계통)"),
    "준주거(%)_정규화": ("Oranges", "준주거지역 (주황색 계통)"),
    "★중심지_지수(합산)": ("PuBu", "중심지 지수 합산 (남색 계통)")
}

# ==========================================
# 0. 다이렉트 AI 통신 엔진
# ==========================================
def get_best_gemini_model(api_key):
    models_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        m_res = requests.get(models_url, timeout=10)
        if m_res.status_code == 200:
            models_data = m_res.json().get('models', [])
            valid_models = [m['name'] for m in models_data if 'generateContent' in m.get('supportedGenerationMethods', [])]
            if not valid_models: return "models/gemini-2.5-pro"
            return next((m for m in valid_models if '2.5-pro' in m.lower()), 
                   next((m for m in valid_models if 'pro' in m.lower()), valid_models[0]))
    except Exception:
        pass
    return "models/gemini-2.5-pro" # fallback

# 스트림릿 캐시를 사용하여 여러 번 불필요한 모델 목록 조회 방지 (Rate Limit 절약)
cached_best_model = None

class GeminiAPIError(Exception):
    pass

def get_gemini_response(prompt, history, api_key, model_override=None):
    global cached_best_model
    
    if model_override:
        target_model = model_override
    else:
        if not cached_best_model:
            cached_best_model = get_best_gemini_model(api_key)
        target_model = cached_best_model
        
    if not target_model.startswith("models/"):
        target_model = f"models/{target_model}"
        
    url = f"https://generativelanguage.googleapis.com/v1beta/{target_model}:generateContent?key={api_key}"
    
    contents = []
    for msg in history:
        role = "model" if msg["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})
    contents.append({"role": "user", "parts": [{"text": prompt}]})
    payload = {"contents": contents}
    headers = {"Content-Type": "application/json"}
    
    retries = 3
    for attempt in range(retries):
        try:
            res = requests.post(url, json=payload, headers=headers, timeout=120)
            if res.status_code == 200:
                return res.json()['candidates'][0]['content']['parts'][0]['text']
            elif res.status_code == 429: # Too Many Requests (Rate Limit)
                if attempt < retries - 1:
                    time.sleep(10 * (attempt + 1)) # 10초, 20초 후 재시도
                    continue
                else:
                    raise GeminiAPIError("Too Many Requests (Rate Limit)")
            else:
                if attempt < retries - 1:
                    time.sleep(5)
                    continue
                raise GeminiAPIError(f"HTTP Error: {res.status_code}")
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(5)
                continue
            raise GeminiAPIError(f"Connection Error: {str(e)}")
    
    raise GeminiAPIError("통신 일시적 실패")



# ==========================================
# 1. API 요청 및 데이터 필터 함수 (기존과 동일)
# ==========================================
def safe_req(url, params=None, retries=3):
    for attempt in range(retries):
        try:
            res = requests.get(url, params=params, timeout=15)
            if res.status_code == 200:
                return res.json()
        except Exception:
            time.sleep(1)
    return {}

def safe_int(val):
    try: return int(val)
    except (ValueError, TypeError): return 0

def get_sgis_token():
    url = "https://sgisapi.kostat.go.kr/OpenAPI3/auth/authentication.json"
    res = safe_req(url, {"consumer_key": SGIS_KEY, "consumer_secret": SGIS_SECRET})
    return res.get("result", {}).get("accessToken")

@st.cache_data(show_spinner=False)
def get_cached_sigungu_list(sido_code):
    result_dict = {"전체": [sido_code]}
    token = get_sgis_token()
    if not token: return result_dict
    url = f"https://sgisapi.kostat.go.kr/OpenAPI3/addr/stage.json?cd={sido_code}&pg_yn=0&accessToken={token}"
    res = safe_req(url)
    if res and "result" in res:
        for item in res["result"]:
            name = item["addr_name"]
            cd = item["cd"]
            parts = name.split()
            if len(parts) == 2 and parts[0].endswith("시") and parts[1].endswith("구"):
                city_name = parts[0]
                if city_name not in result_dict:
                    result_dict[city_name] = []
                result_dict[city_name].append(cd) 
            else:
                result_dict[name] = [cd]
    return result_dict

def get_sgis_dong(target_codes, year, token):
    url = "https://sgisapi.kostat.go.kr/OpenAPI3/boundary/hadmarea.geojson"
    def fetch_dongs(code):
        res = safe_req(url, {"accessToken": token, "year": year, "adm_cd": code, "low_search": "1"})
        features = res.get("features", [])
        if not features: return []
        sample_cd = features[0]["properties"]["adm_cd"]
        if len(sample_cd) < 7:
            sub_dongs = []
            for f in features:
                sub_dongs.extend(fetch_dongs(f["properties"]["adm_cd"]))
            return sub_dongs
        else:
            return features

    dong_list = []
    for code in target_codes:
        features = fetch_dongs(code)
        if features:
            dong_list.append(gpd.GeoDataFrame.from_features(features))
    if not dong_list: return gpd.GeoDataFrame()
    gdf = pd.concat(dong_list, ignore_index=True)
    gdf.set_crs(epsg=5179, inplace=True)
    return gdf

def get_sgis_stats(dong_gdf, year, token):
    pop_dict, biz_dict, worker_dict = {}, {}, {}
    parent_codes = dong_gdf['adm_cd'].astype(str).str[:5].unique()
    for gu in parent_codes:
        pop_url = "https://sgisapi.kostat.go.kr/OpenAPI3/stats/searchpopulation.json"
        pop_res = safe_req(pop_url, {"year": year, "adm_cd": gu, "low_search": "1", "accessToken": token})
        if pop_res.get("errCd") == 0:
            for item in pop_res.get("result", []):
                pop_dict[item["adm_cd"]] = safe_int(item.get("tot_ppltn", item.get("population", 0)))
        biz_url = "https://sgisapi.kostat.go.kr/OpenAPI3/stats/company.json"
        biz_res = safe_req(biz_url, {"year": year, "adm_cd": gu, "low_search": "1", "accessToken": token})
        if biz_res.get("errCd") == 0:
            for item in biz_res.get("result", []):
                biz_dict[item["adm_cd"]] = safe_int(item.get("corp_cnt", 0))
                worker_dict[item["adm_cd"]] = safe_int(item.get("tot_worker", 0))
    return pop_dict, biz_dict, worker_dict

def get_vworld_zoning_bbox(minx, miny, maxx, maxy, key, depth=0):
    url = "https://api.vworld.kr/req/wfs"
    bbox_str = f"{minx},{miny},{maxx},{maxy},EPSG:3857"
    params = {
        "key": key, "domain": "http://localhost", "SERVICE": "WFS",
        "VERSION": "1.1.0", "REQUEST": "GetFeature", "TYPENAME": "lt_c_uq111",
        "OUTPUT": "application/json", "SRSNAME": "EPSG:3857",
        "MAXFEATURES": "1000", "BBOX": bbox_str
    }
    res = safe_req(url, params)
    if "features" not in res or len(res["features"]) == 0: 
        return gpd.GeoDataFrame() 
    gdf = gpd.GeoDataFrame.from_features(res["features"])
    gdf.set_crs(epsg=3857, inplace=True)
    if len(gdf) >= 1000 and depth < 3:
        midx, midy = (minx + maxx) / 2, (miny + maxy) / 2
        df1 = get_vworld_zoning_bbox(minx, miny, midx, midy, key, depth+1)
        df2 = get_vworld_zoning_bbox(midx, miny, maxx, midy, key, depth+1)
        df3 = get_vworld_zoning_bbox(minx, midy, midx, maxy, key, depth+1)
        df4 = get_vworld_zoning_bbox(midx, midy, maxx, maxy, key, depth+1)
        return pd.concat([df1, df2, df3, df4], ignore_index=True)
    return gdf


# ==========================================
# 2. 메인 UI 및 데이터 분석
# ==========================================
header_col1, header_col2 = st.columns([1.5, 1])

with header_col1:
    st.markdown("<br><h2 style='margin-bottom: 0;'>도시·군기본계획 도시공간구조</h2><h2 style='margin-top: 0;'>설정 자동화 시스템</h2>", unsafe_allow_html=True)

with header_col2:
    st.markdown("##### 분석범위선택")
    hc1, hc2 = st.columns(2)
    with hc1:
        selected_sido = st.selectbox("• 시도 선택", list(SIDO_MAP.keys()), index=5)
        sido_code = SIDO_MAP[selected_sido]
        sigungu_dict = get_cached_sigungu_list(sido_code)
        selected_sigungu_name = st.selectbox("• 시군구 선택", list(sigungu_dict.keys()))
    with hc2:
        target_year = st.selectbox("• 기준년도", ["2025", "2024", "2023", "2022", "2021", "2020"], index=2)
        future_year = st.selectbox("• 목표년도", ["2040", "2035", "2030", "2045", "2050"])

st.markdown("<hr style='border: 1px solid #4A7CB6;'>", unsafe_allow_html=True)

if 'analysis_done_A' not in st.session_state: st.session_state['analysis_done_A'] = False
if 'analysis_done_B' not in st.session_state: st.session_state['analysis_done_B'] = False
if 'analysis_done_C' not in st.session_state: st.session_state['analysis_done_C'] = False

col_a, col_b = st.columns(2)

# --- Step A: 정량 분석 ---
with col_a:
    ac1, ac2 = st.columns([2.5, 1])
    ac1.markdown("#### A.[현재 : (정량)중심지 현황]")
    btn_a = ac2.button("분석 시작", key="btn_a", use_container_width=True, type="primary")
    
    st.markdown("**중심지지수 산출 가중치 설정**")
    w1, w2 = st.columns(2)
    with w1:
        w_pop = st.number_input("• 인구", value=1.0, step=0.1, min_value=0.0)
        w_biz = st.number_input("• 사업체수", value=1.0, step=0.1, min_value=0.0)
        w_worker = st.number_input("• 종사자수", value=1.0, step=0.1, min_value=0.0)
    with w2:
        w_zone1 = st.number_input("• 중심상업지역 비율", value=1.0, step=0.1, min_value=0.0)
        w_zone2 = st.number_input("• 일반상업지역 비율", value=1.0, step=0.1, min_value=0.0)
        w_zone3 = st.number_input("• 근린상업지역 비율", value=1.0, step=0.1, min_value=0.0)
        w_zone4 = st.number_input("• 준주거지역 비율", value=1.0, step=0.1, min_value=0.0)
        
    weights_map = {"인구(명)": w_pop, "사업체(수)": w_biz, "종사자(수)": w_worker, "중심상업(%)": w_zone1, "일반상업(%)": w_zone2, "근린상업(%)": w_zone3, "준주거(%)": w_zone4}

    if btn_a:
        progress_text = "통계청 인증 및 분석 준비 중..."
        my_bar = st.progress(0, text=progress_text)
        
        sgis_token = get_sgis_token()
        if not sgis_token:
            st.error("API 키가 올바르게 설정되지 않았습니다.")
            st.stop()
            
        target_codes = sigungu_dict[selected_sigungu_name]
        
        my_bar.progress(20, text="[1/4] 통계청 행정동 경계 및 데이터 수집 중...")
        dong_gdf = get_sgis_dong(target_codes, target_year, sgis_token)
        pop_dict, biz_dict, worker_dict = get_sgis_stats(dong_gdf, target_year, sgis_token)
        dong_gdf['adm_cd'] = dong_gdf['adm_cd'].astype(str)
        dong_gdf['dong_area_sqm'] = dong_gdf.geometry.area
        dong_area_dict = dict(zip(dong_gdf['adm_cd'], dong_gdf['dong_area_sqm']))
        dong_3857 = dong_gdf.to_crs(epsg=3857)
    
        my_bar.progress(50, text="[2/4] 국토부 용도지역 데이터 병합 중...")
        zoning_list = []
        for idx, row in dong_3857.iterrows():
            b = row.geometry.bounds 
            zdf = get_vworld_zoning_bbox(b[0], b[1], b[2], b[3], VWORLD_KEY)
            if not zdf.empty: zoning_list.append(zdf)
                
        zoning_gdf = pd.concat(zoning_list, ignore_index=True) if zoning_list else gpd.GeoDataFrame()
        target_mapping = {'UQA210': '중심상업', 'UQA220': '일반상업', 'UQA230': '근린상업', 'UQA130': '준주거'}
        if not zoning_gdf.empty:
            code_col = 'ucode' if 'ucode' in zoning_gdf.columns else [c for c in zoning_gdf.columns if 'code' in c.lower() or 'cde' in c.lower()][0]
            zoning_gdf = zoning_gdf[zoning_gdf[code_col].isin(target_mapping.keys())]
            zoning_gdf['target_zone'] = zoning_gdf[code_col].map(target_mapping)
            zoning_gdf['geom_wkt'] = zoning_gdf.geometry.to_wkt()
            zoning_gdf = zoning_gdf.drop_duplicates(subset=['geom_wkt']).drop(columns=['geom_wkt'])
        
        my_bar.progress(80, text="[3/4] 공간 연산 중...")
        zoning_gdf = zoning_gdf.to_crs(epsg=5179) if not zoning_gdf.empty else zoning_gdf
        dong_gdf['geometry'] = dong_gdf.geometry.buffer(0)
        if not zoning_gdf.empty: zoning_gdf['geometry'] = zoning_gdf.geometry.buffer(0)
        
        intersected = gpd.overlay(dong_gdf, zoning_gdf, how='intersection') if not zoning_gdf.empty else gpd.GeoDataFrame()
        if not intersected.empty:
            intersected['area_sqm'] = intersected.geometry.area
            summary = intersected.groupby(['adm_cd', 'target_zone'])['area_sqm'].sum().reset_index()
            pivot_df = summary.pivot(index='adm_cd', columns='target_zone', values='area_sqm').fillna(0)
        else:
            pivot_df = pd.DataFrame()
            
        all_codes = dong_gdf['adm_cd'].unique()
        pivot_df = pivot_df.reindex(all_codes, fill_value=0.0)
        pivot_df['★동전체면적'] = pivot_df.index.map(dong_area_dict).fillna(0)
        
        my_bar.progress(95, text="[4/4] 중심지 지수 산출 중...")
        final_rows = []
        for idx, row in dong_gdf.iterrows():
            code = row['adm_cd']
            name_parts = str(row['adm_nm']).split()
            sido = name_parts[0] if len(name_parts) > 0 else "-"
            sigungu = name_parts[1] if len(name_parts) > 1 else "-"
            dong = name_parts[-1] if len(name_parts) > 0 else "-"
            if len(name_parts) >= 4 and name_parts[1].endswith("시") and name_parts[2].endswith("구"):
                sigungu, dong = name_parts[1], f"{name_parts[2]} {name_parts[-1]}"
                
            row_data = {"adm_cd": code, "시도": sido, "시군구": sigungu, "행정동": dong,
                        "인구(명)": pop_dict.get(code, 0), "사업체(수)": biz_dict.get(code, 0), "종사자(수)": worker_dict.get(code, 0)}
            for zone in target_mapping.values():
                area = pivot_df.loc[code, zone] if zone in pivot_df.columns else 0.0
                ratio = (area / pivot_df.loc[code, '★동전체면적']) * 100 if pivot_df.loc[code, '★동전체면적'] > 0 else 0.0
                row_data[f"{zone}(㎡)"] = round(area, 2)
                row_data[f"{zone}(%)"] = round(ratio, 2)
            final_rows.append(row_data)
            
        final_df = pd.DataFrame(final_rows)
        norm_cols = ["인구(명)", "사업체(수)", "종사자(수)", "중심상업(%)", "일반상업(%)", "근린상업(%)", "준주거(%)"]
        norm_df = final_df.copy()
        for col in norm_cols:
            min_val, max_val = norm_df[col].min(), norm_df[col].max()
            norm_df[f"{col}_정규화"] = 0.0 if max_val == min_val else round(((norm_df[col] - min_val) / (max_val - min_val)) * weights_map[col], 4)
                
        scaled_cols = [f"{col}_정규화" for col in norm_cols]
        norm_df["★중심지_지수(합산)"] = norm_df[scaled_cols].sum(axis=1).round(4)
        norm_df = norm_df.sort_values(by="★중심지_지수(합산)", ascending=False).reset_index(drop=True)
        
        st.session_state['dong_gdf'] = dong_gdf
        st.session_state['norm_df'] = norm_df
        st.session_state['export_raw_df'] = final_df.drop(columns=["adm_cd"])
        st.session_state['display_norm_df'] = norm_df.drop(columns=["adm_cd"])[["시도", "시군구", "행정동"] + scaled_cols + ["★중심지_지수(합산)"]]
        st.session_state['result_sido'] = selected_sido
        st.session_state['result_sigungu'] = selected_sigungu_name
        st.session_state['result_year'] = target_year
        st.session_state['analysis_done_A'] = True
        
        my_bar.progress(100, text="✨ A단계 정량 분석 완료!")
        st.success("정량적 현황 데이터 산출이 완료되었습니다!")

# --- Step B: 정성 분석 ---
with col_b:
    bc1, bc2 = st.columns([2.5, 1])
    bc1.markdown("#### B.[미래 : (정성)도시공간구조 변화]")
    btn_b = bc2.button("분석 시작", key="btn_b", use_container_width=True, type="primary")
    
    st.markdown("**분석 AI모델 & 반영사항**")
    b1, b2 = st.columns(2)
    with b1:
        st.markdown("<div style='font-size: 14px;'>분석 AI모델</div>", unsafe_allow_html=True)
        selected_ai_model_qual = st.radio("AI모델 선택", 
            ["GEMINI 2.5 Flash", "GEMINI 2.5 Pro"], 
            key="qual_model", label_visibility="collapsed")
    with b2:
        st.markdown("<div style='font-size: 14px;'>반영사항</div>", unsafe_allow_html=True)
        use_plan = st.checkbox("상위및관련계획", value=True)
        use_adj = st.checkbox("인접 시·군 공간구조", value=True)
        use_policy = st.checkbox("지역현안사항", value=True)
        use_deep_research = st.checkbox("- deep research 반영", value=True)

    if btn_b:
        with st.spinner("문서를 읽고 현황 분석 요약본을 작성 중입니다... (약 1분 소요)"):
            if use_plan:
                plan_text = st.session_state.get('plan_text_cache', '') if uploaded_plan_files else read_folder_documents("01. 상위계획")
            else:
                plan_text = "반영안함"
                
            if use_adj:
                adj_text = st.session_state.get('adj_text_cache', '') if uploaded_adj_files else read_folder_documents("02. 타지자체 도시·군기본계획")
            else:
                adj_text = "반영안함"
            
            if use_policy:
                policy_text = read_folder_documents("03. 지역정책사항")
                if not policy_text.strip() and use_deep_research:
                    policy_instruction = f"제공된 지역정책 자료가 없습니다. 당신의 자체 지식 데이터베이스를 활용하여 심층 리서치(Deep Research)를 수행하고, '{selected_sido} {selected_sigungu_name}'의 최신 주요 지역 현안 및 이슈 사항을 직접 도출하여 반영하십시오."
                elif not policy_text.strip():
                    policy_instruction = "반영안함"
                else:
                    policy_instruction = policy_text
            else:
                policy_instruction = "반영안함"
            
            # --- 🚀 [신규 기능] 업로드된 공간 데이터 자동 텍스트 변환 병합 ---
            spatial_insights = ""
            if uploaded_spatial_files and st.session_state.get('analysis_done_A') and 'dong_gdf' in st.session_state:
                with st.spinner("업로드된 공간 데이터(SHP/GeoJSON)와 행정동 경계를 교차 분석 중입니다..."):
                    try:
                        # 1. 임시 디렉토리에 파일 저장
                        temp_dir = tempfile.mkdtemp()
                        saved_files = []
                        target_read_file = None
                        
                        for uf in uploaded_spatial_files:
                            file_path = os.path.join(temp_dir, uf.name)
                            with open(file_path, "wb") as f:
                                f.write(uf.getbuffer())
                            saved_files.append(file_path)
                            
                            # 읽어들일 주 파일 식별
                            if uf.name.lower().endswith('.shp') or uf.name.lower().endswith('.geojson') or uf.name.lower().endswith('.json'):
                                target_read_file = file_path
                        
                        if target_read_file:
                            # 2. GeoDataFrame으로 열기
                            uploaded_gdf = gpd.read_file(target_read_file)
                            
                            # 3. 좌표계 통일 (dong_gdf와 동일하게)
                            dong_gdf = st.session_state['dong_gdf']
                            if uploaded_gdf.crs is None:
                                uploaded_gdf.set_crs(epsg=5179, inplace=True) # 기본 5179 가정
                            else:
                                uploaded_gdf = uploaded_gdf.to_crs(dong_gdf.crs)
                            
                            # 4. 공간 조인 (Spatial Join) 을 통해 어느 행정동에 걸치는지 파악
                            join_gdf = gpd.sjoin(uploaded_gdf, dong_gdf[['adm_cd', 'adm_nm', 'geometry']], how='inner', predicate='intersects')
                            
                            if not join_gdf.empty:
                                spatial_insights += "\n[추가 분석 데이터: 업로드된 공간 기반 현안/개발사업]\n"
                                # 행정동별로 묶어서 요약
                                grouped = join_gdf.groupby('adm_nm').size().reset_index(name='count')
                                dongs_affected = ", ".join(grouped['adm_nm'].tolist())
                                spatial_insights += f"- 사용자가 업로드한 공간 도면 데이터(SHP/GeoJSON)를 행정동 경계와 공간 연산(Spatial Intersection)한 결과입니다.\n"
                                spatial_insights += f"- 해당 사업/노선/구역계는 다음 지역을 직접적으로 관통하거나 포함하고 있습니다: **{dongs_affected}**.\n"
                                spatial_insights += f"- 따라서 이 지역들({dongs_affected})은 신규 인프라 확충 또는 개발 사업으로 인해 미래 물리적 공간구조(중심지 위상)가 크게 상향 변화할 잠재력이 지대합니다. 종합 분석 시 이들 행정동의 전략적 우선순위를 높게 평가하십시오.\n"
                            else:
                                spatial_insights += "\n[추가 분석 데이터: 공간 연산 결과]\n- 업로드된 공간 데이터가 현재 대상 시·군·구 행정동 경계와 겹치지 않습니다. 좌표계를 확인하거나 대상지 범위를 확인하십시오.\n"
                        else:
                            spatial_insights += "\n- 공간 데이터를 처리할 수 없습니다. .shp 파일이나 .geojson 메인 파일이 누락되었을 수 있습니다."
                            
                    except Exception as e:
                        spatial_insights += f"\n- 공간 데이터 변환 중 오류 발생: {str(e)}"
            
            # 최종 정책 사항에 합치기
            if spatial_insights:
                if policy_instruction == "반영안함": policy_instruction = ""
                policy_instruction += "\n" + spatial_insights

            qual_prompt = f"""
            작업 목표: [{selected_sido} {selected_sigungu_name}]의 정성적 현황 시사점을 분석하여 공공기관용 요약 보고서를 작성합니다.

            엄격한 규칙:
            1. "안녕하십니까", "제가 분석하겠습니다", "20년 경력의..." 와 같은 대화형 문구와 인사말을 **절대 사용하지 마십시오.**
            2. 문장 구조는 '~함.', '~임.', '~할 것임.' 등 명사형 종결어미 형태의 **개조식(Bullet point) 문장**으로만 작성하십시오.
            3. 분석가의 주관적 감상이나 메타 발언(수치 지표 배제 등)을 일절 제외하고 순수하게 행정 보고서의 핵심 팩트와 시사점 내용만을 직관적으로 서술하십시오.
            4. 아래 4개의 목차를 반드시 작성하되, 각 목차의 시작 지점에 구분자 `===SECTION_1===`, `===SECTION_2===`, `===SECTION_3===`, `===SECTION_4===`를 정확히 기입하십시오. (다른 텍스트 없이 구분자만 단독 줄에 작성)

            [1. 상위계획 및 관련계획 방향]
            {plan_text}

            [2. 인접 지자체 공간구조 연계 사항]
            {adj_text}
            
            [3. 지역 정책 사항]
            {policy_instruction}
            =============================

            [최종 출력 목차 지시사항 및 구분별 작성 내용]
            (주의: 각 섹션 시작 부분에 '1. 상위 및 관련계획 요약' 등과 같은 대제목을 절대 쓰지 마십시오. 오직 본문(글머리 기호 내용)부터 바로 출력하십시오.)
            ===SECTION_1===
            - 상위 및 관련계획 방향 시사점 내용부터 작성
            ===SECTION_2===
            - 인접 시·군 공간구조 요약 시사점 내용부터 작성
            ===SECTION_3===
            - 지역현안사항 종합 요약 내용부터 작성
            ===SECTION_4===
            - 위 1~3번을 통합한 종합 결과 진단 내용부터 작성
            """
            
            model_name = "models/gemini-2.5-flash" if "Flash" in selected_ai_model_qual else "models/gemini-2.5-pro"
            try:
                result_qual = get_gemini_response(qual_prompt, [], GEMINI_API_KEY, model_override=model_name)
                
                st.session_state['qual_report'] = result_qual
                st.session_state['analysis_done_B'] = True
                st.success("✨ B단계 정성적 현황 분석이 완료되었습니다!")
            except GeminiAPIError as e:
                st.error('분석할 문서의 양이 너무 많거나 서버 응답이 지연되었습니다. 문서 분량을 줄여서 다시 시도해 주세요.')

st.markdown("<br><hr>", unsafe_allow_html=True)

# ==========================================
# 🚀 Step C: 최종 종합 도출 UI
# ==========================================
cc1, cc2 = st.columns([5, 1])
cc1.markdown("#### C. 최종 종합 도시공간구조 구상 (A+B)")
btn_c = cc2.button("분석 시작", key="btn_c", use_container_width=True, type="primary")

if btn_c:
    if not (st.session_state.get('analysis_done_A') and st.session_state.get('analysis_done_B')):
        st.warning("⚠️ C단계를 진행하려면 먼저 상단의 A단계(정량)와 B단계(정성) 분석을 모두 완료해야 합니다!")
    else:
        with st.spinner("AI 수석 도시계획가가 종합 분석을 진행합니다... (약 1분 소요)"):
            
            sample_text = read_folder_documents("00. 샘플")
            top_zones = st.session_state['display_norm_df'].head(15).to_csv(index=False)
            qual_summary = st.session_state['qual_report']
            
            ai_prompt = f"""
            작업 목표: [{st.session_state['result_sido']} {st.session_state['result_sigungu']}]의 {future_year}년 목표 미래 도시공간구조안(도심, 부도심, 지역중심 설정 등)을 도출하는 공공기관용 종합 보고서를 작성합니다.

            엄격한 규칙 (절대 엄수):
            1. "네, 알겠습니다", "수석 도시계획가로서...", "본 보고서는...", "분석 결과입니다" 등의 대화형 인사말, 서론, 결론 요약 등은 **절대 출력하지 마십시오.**
            2. 문장 구조는 '~함.', '~임.', '~할 것임.' 등 명사형 또는 '-(으)ㅁ/기'로 끝나는 **개조식 객관적 문체**로만 작성하십시오.
            3. 당신의 AI 정체성(지식 기반 활용 등)에 대한 언급을 일절 금지합니다.
            4. 오직 아래 [최종 출력 목차 지시사항]의 1번부터 4번까지의 대제목과 그 내용만 **마크다운(Markdown) 형식**으로 깔끔하게 바로 출력하십시오.

            🚨 [가장 중요한 엄수 사항: 00. 샘플의 용도 제한] 🚨
            아래 제공되는 [00. 샘플]은 오직 '보고서의 목차 구조 및 논리 전개 방식'을 흉내 내기 위한 용도입니다. 
            샘플의 제목, 특정 지역명(도시 이름), 구체적 구상안 등의 내용은 절대 출력물에 포함하지 마십시오. 오직 분석 대상인 [{st.session_state['result_sido']} {st.session_state['result_sigungu']}]에 맞게 작성되어야 합니다.

            =============================
            [00. 작성 스타일 벤치마킹 샘플 (형식만 참고할 것! 내용 반영 금지!)]
            {sample_text[:4000]}
            =============================

            자료 1과 자료 2의 내용만을 결합하여 작성하십시오:

            [1. 정량적 분석 결과 (현재 중심지 지수 상위 15개 행정동 요약)]
            {top_zones}

            [2. 정성적 분석 전문가 요약본]
            {qual_summary}
            =============================

            [최종 출력 목차 지시사항]
            1. 현황 및 여건 분석 종합 (정량지수와 정성분석의 시사점 융합)
            2. 미래 도시공간구조 개편의 기본방향 (인접 지자체 연계성 강점 포함)
            3. 공간구조 대안 설정 및 최종안 도출 (도심-부도심 등 구체적인 행정동 위계 명시)
            4. 중심지별 육성(특화) 방안
            """
            
            # Using the Pro model for the final comprehensive synthesis by default (or fetching from fallback)
            model_name = "models/gemini-2.5-pro"
            try:
                result_report = get_gemini_response(ai_prompt, [], GEMINI_API_KEY, model_override=model_name)
                
                st.session_state['generated_report'] = result_report
                st.session_state['analysis_done_C'] = True
                st.success("✨ C단계 최총 종합 구상이 도출되었습니다!")
            except GeminiAPIError as e:
                st.error('분석할 문서의 양이 너무 많거나 서버 응답이 지연되었습니다. 문서 분량을 줄여서 다시 시도해 주세요.')

st.markdown("<hr style='border: 2px solid #ddd; margin-top: 5px; margin-bottom: 5px;'>", unsafe_allow_html=True)

# ==========================================
# 📊 분석 결과 탭 (A / B / C 파트)
# ==========================================

# A, B, C 메인 섹션 라디오 버튼 (가로형)
main_tab = st.radio("분석 결과 확인", ["A. 정량 분석 결과", "B. 정성 분석 요약", "C. 최종 종합 구상"], horizontal=True, label_visibility="collapsed")

if main_tab == "A. 정량 분석 결과":
    if not st.session_state.get('analysis_done_A'):
        st.info("A단계(정량) 분석을 먼저 실행해 주세요.")
    else:
        t_a1, t_a2 = st.tabs(["1. 항목별 주요 내용 요약", "2. 중심지지수 종합 결과"])
        
        with t_a1:
            st.markdown("### 📊 분석 항목별 핵심 지표 현황")
            req_item = st.selectbox("조회할 세부 지표 선택:", list(MAP_COLORS.keys()), format_func=lambda x: MAP_COLORS[x][1], key="a1_select")
            
            # Map generation and Table
            c1, c2 = st.columns([1, 1])
            with c1:
                st.markdown(f"**[{MAP_COLORS[req_item][1]}] 상위 10개 행정동**")
                # Need to find the un-normalized column name for display if available, but let's just sort by the selected normalized col
                # or actually, just show the selected metric column
                original_col_name = req_item.replace('_정규화', '') if '_정규화' in req_item else req_item
                display_cols = ['행정동', original_col_name] if original_col_name in st.session_state['display_norm_df'].columns else ['행정동', req_item]
                top10_df = st.session_state['display_norm_df'].sort_values(by=req_item, ascending=False).head(10)[display_cols]
                top10_df.index = range(1, len(top10_df) + 1)
                st.dataframe(top10_df, use_container_width=True)
                
            with c2:
                # `st.session_state['dong_gdf']`에는 'adm_cd', 'geometry' 등이 있고, '행정동'은 `norm_df`에 존재.
                # merge 시 norm_df 전체 혹은 필요한 컬럼을 확실히 가져옴
                map_gdf = st.session_state['dong_gdf'].merge(st.session_state['norm_df'][['adm_cd', '행정동', req_item]], on='adm_cd')
                fig, ax = plt.subplots(figsize=(8, 8))
                
                # 섬(도서) 분리 로직 (인천 - 옹진군, 신안군 등)
                far_islands = ["백령면", "대청면", "연평면", "흑산면"]
                island_mask = map_gdf['행정동'].isin(far_islands)
                
                main_gdf = map_gdf[~island_mask]
                island_gdf = map_gdf[island_mask]
                
                # 메인 맵 그리기
                main_gdf_bounds = main_gdf.copy()
                main_gdf.plot(ax=ax, facecolor='lightgray', edgecolor='white', linewidth=0.8)
                # 분리형(이산형) 범례를 위해 scheme='equal_interval' 적용
                main_plot = main_gdf.plot(
                    column=req_item, cmap=MAP_COLORS[req_item][0], ax=ax, legend=True, 
                    scheme='equal_interval', k=5, edgecolor='black', linewidth=0.5, 
                    legend_kwds={'loc': 'lower right', 'fontsize': 8, 'title': '지표구간', 'title_fontsize': 9, 'bbox_to_anchor': (1.15, 0)}
                )
                
                # [신규 추가] 사용자가 업로드한 공간자료(SHP, GeoJSON)가 있으면 지도 위에 오버레이 그림
                uploaded_spatial_gdf = parse_uploaded_spatial_files(uploaded_spatial_files)
                if uploaded_spatial_gdf is not None:
                    try:
                        if uploaded_spatial_gdf.crs is None:
                            uploaded_spatial_gdf.set_crs(epsg=5179, inplace=True)
                        overlay_gdf = uploaded_spatial_gdf.to_crs(main_gdf.crs)
                        
                        # 화면을 넘기지 않기 위해 교차하는 부분만 추출하거나 클리핑할 수 있으나, 단순 중첩 표시
                        overlay_gdf.plot(ax=ax, facecolor='none', edgecolor='red', linewidth=2.5, linestyle='--', alpha=0.7)
                    except Exception:
                        pass
                
                # 메인 영역 라벨링 (지시선 포함)
                main_gdf['rep_pt'] = main_gdf.geometry.representative_point()
                for i, (idx, row) in enumerate(main_gdf.iterrows()):
                    angle = (i * 137.5) % 360
                    rad = math.radians(angle)
                    offset_dist = 25 
                    
                    ax.annotate(
                        text=row['행정동'], 
                        xy=(row['rep_pt'].x, row['rep_pt'].y),
                        xytext=(offset_dist * math.cos(rad), offset_dist * math.sin(rad)),
                        textcoords='offset points',
                        horizontalalignment='center', 
                        verticalalignment='center',
                        fontsize=8, 
                        color='black',
                        path_effects=[patheffects.withStroke(linewidth=2, foreground='white')],
                        arrowprops=dict(arrowstyle="-", color="black", lw=0.6, alpha=0.6),
                        fontproperties=custom_fontprops
                    )
                
                # 원거리 도서지역 (삽도 - Inset Map) 처리
                if not island_gdf.empty:
                    # 메인 맵의 경계(Zoom)를 내륙(+근거리 섬) 위주로 맞춰줌
                    minx, miny, maxx, maxy = main_gdf.total_bounds
                    # 여백 5% 반영
                    dx = maxx - minx
                    dy = maxy - miny
                    ax.set_xlim(minx - dx*0.05, maxx + dx*0.05)
                    ax.set_ylim(miny - dy*0.05, maxy + dy*0.05)
                
                    # 삽도 축(Axes) 생성: 좌측 상단 여백에 작게!
                    ax_inset = ax.inset_axes([0.02, 0.65, 0.25, 0.30])
                    # ax_inset 보더 박스 설정
                    for spine in ax_inset.spines.values():
                        spine.set_edgecolor('gray')
                        spine.set_linewidth(1)
                    
                    # 삽도에 도서지역 그리기 (메인과 동일한 colormap)
                    vmin, vmax = map_gdf[req_item].min(), map_gdf[req_item].max()
                    island_gdf.plot(ax=ax_inset, facecolor='lightgray', edgecolor='white', linewidth=0.8)
                    island_gdf.plot(column=req_item, cmap=MAP_COLORS[req_item][0], ax=ax_inset, legend=False, scheme='equal_interval', k=5, edgecolor='black', linewidth=0.5)
                    
                    # 삽도 라벨링
                    island_gdf['rep_pt'] = island_gdf.geometry.representative_point()
                    for i, (idx, row) in enumerate(island_gdf.iterrows()):
                        ax_inset.annotate(
                            text=row['행정동'], 
                            xy=(row['rep_pt'].x, row['rep_pt'].y),
                            xytext=(0, 10),
                            textcoords='offset points',
                            horizontalalignment='center', 
                            verticalalignment='center',
                            fontsize=7, 
                            color='black',
                            path_effects=[patheffects.withStroke(linewidth=1.5, foreground='white')],
                            fontproperties=custom_fontprops
                        )
                    ax_inset.set_xticks([])
                    ax_inset.set_yticks([])
                
                ax.set_axis_off()
                # 이모지 제거하여 폰트 깨짐 방지
                ax.set_title(f"{MAP_COLORS[req_item][1]} 분포도", fontsize=14, pad=15, fontweight='bold', fontproperties=custom_fontprops)
                st.pyplot(fig)
                
        with t_a2:
            st.markdown("### 🏆 정량적 중심지지수 최종 종합 결과")
            c1, c2 = st.columns([1, 1])
            with c1:
                st.markdown("**[최종 중심지지수 (합산)] 상위 10개 행정동**")
                final_top10 = st.session_state['display_norm_df'].sort_values(by="★중심지_지수(합산)", ascending=False).head(10)[['행정동', '★중심지_지수(합산)']]
                final_top10.index = range(1, len(final_top10) + 1)
                st.dataframe(final_top10, use_container_width=True)
                
                st.markdown(f"**💡 핵심 시사점 (요약):**")
                st.info(f"선택하신 지역({st.session_state['result_sigungu']}) 내에서 가장 높은 중심지 지수를 기록한 곳은 **'{final_top10.iloc[0]['행정동']}'** 이며, 이어 **'{final_top10.iloc[1]['행정동']}'**, **'{final_top10.iloc[2]['행정동']}'** 순으로 나타났습니다. 이는 설정된 개별 지표 및 가중치 조건 하에서 해당 지역들이 가장 핵심적인 도심/부도심 물리적 위상을 지니고 있음을 방증합니다.")
            with c2:
                # `st.session_state['dong_gdf']`에는 'adm_cd', 'geometry' 등이 있고, '행정동'은 `norm_df`에 존재.
                map_gdf = st.session_state['dong_gdf'].merge(st.session_state['norm_df'][['adm_cd', '행정동', '★중심지_지수(합산)']], on='adm_cd')
                fig, ax = plt.subplots(figsize=(8, 8))
                
                # 동일한 섬 분리 로직 적용
                far_islands = ["백령면", "대청면", "연평면", "흑산면"]
                island_mask = map_gdf['행정동'].isin(far_islands)
                
                main_gdf = map_gdf[~island_mask]
                island_gdf = map_gdf[island_mask]

                # 메인 맵 그리기
                main_gdf.plot(ax=ax, facecolor='lightgray', edgecolor='white', linewidth=0.8)
                main_gdf.plot(
                    column="★중심지_지수(합산)", cmap="PuBu", ax=ax, legend=True, 
                    scheme='equal_interval', k=5, edgecolor='black', linewidth=0.5, 
                    legend_kwds={'loc': 'lower right', 'fontsize': 8, 'title': '지수구간', 'title_fontsize': 9, 'bbox_to_anchor': (1.15, 0)}
                )
                
                # [신규 추가] 사용자가 업로드한 공간자료(SHP, GeoJSON) 지도 위에 오버레이
                if uploaded_spatial_gdf is not None:
                    try:
                        overlay_gdf = uploaded_spatial_gdf.to_crs(main_gdf.crs)
                        overlay_gdf.plot(ax=ax, facecolor='none', edgecolor='red', linewidth=2.5, linestyle='--', alpha=0.7)
                    except Exception:
                        pass
                
                # 메인 라벨링
                main_gdf['rep_pt'] = main_gdf.geometry.representative_point()
                for i, (idx, row) in enumerate(main_gdf.iterrows()):
                    if row["★중심지_지수(합산)"] > 0:
                        angle = (i * 137.5) % 360
                        rad = math.radians(angle)
                        offset_dist = 25
                        
                        ax.annotate(
                            text=row['행정동'], 
                            xy=(row['rep_pt'].x, row['rep_pt'].y),
                            xytext=(offset_dist * math.cos(rad), offset_dist * math.sin(rad)),
                            textcoords='offset points',
                            horizontalalignment='center', 
                            verticalalignment='center',
                            fontsize=8, 
                            color='black',
                            path_effects=[patheffects.withStroke(linewidth=2, foreground='white')],
                            arrowprops=dict(arrowstyle="-", color="black", lw=0.6, alpha=0.6),
                            fontproperties=custom_fontprops
                        )
                
                # 삽도(Inset Map) 생성 영역
                if not island_gdf.empty:
                    minx, miny, maxx, maxy = main_gdf.total_bounds
                    dx = maxx - minx
                    dy = maxy - miny
                    # 삽도가 그려진다는 뜻은 전체 뷰가 과도하게 확장되지 않게 메인에 Focus를 둔다는 의미
                    ax.set_xlim(minx - dx*0.05, maxx + dx*0.05)
                    ax.set_ylim(miny - dy*0.05, maxy + dy*0.05)
                    
                    ax_inset = ax.inset_axes([0.02, 0.65, 0.25, 0.30])
                    for spine in ax_inset.spines.values():
                        spine.set_edgecolor('gray')
                        spine.set_linewidth(1)
                    
                    vmin, vmax = map_gdf["★중심지_지수(합산)"].min(), map_gdf["★중심지_지수(합산)"].max()
                    island_gdf.plot(ax=ax_inset, facecolor='lightgray', edgecolor='white', linewidth=0.8)
                    island_gdf.plot(column="★중심지_지수(합산)", cmap="PuBu", ax=ax_inset, legend=False, scheme='equal_interval', k=5, edgecolor='black', linewidth=0.5)
                    
                    island_gdf['rep_pt'] = island_gdf.geometry.representative_point()
                    for i, (idx, row) in enumerate(island_gdf.iterrows()):
                        if row["★중심지_지수(합산)"] > 0:
                            ax_inset.annotate(
                                text=row['행정동'], 
                                xy=(row['rep_pt'].x, row['rep_pt'].y),
                                xytext=(0, 10),
                                textcoords='offset points',
                                horizontalalignment='center', 
                                verticalalignment='center',
                                fontsize=7, 
                                color='black',
                                path_effects=[patheffects.withStroke(linewidth=1.5, foreground='white')],
                                fontproperties=custom_fontprops
                            )
                    ax_inset.set_xticks([])
                    ax_inset.set_yticks([])

                ax.set_axis_off()
                # 이모지 제거하여 폰트 깨짐 방지
                ax.set_title("최종 종합 중심지지수 분포 시각화", fontsize=14, pad=15, fontweight='bold', fontproperties=custom_fontprops)
                st.pyplot(fig)

elif main_tab == "B. 정성 분석 요약":
    if not st.session_state.get('analysis_done_B'):
         st.info("B단계(정성) 분석을 먼저 실행해 주세요.")
    else:
        t_b1, t_b2, t_b3, t_b4 = st.tabs(["상위 및 관련계획", "인접 시·군 공간구조", "지역현안사항", "종합"])
        
        qual_report = st.session_state['qual_report']
        import re
        sections = re.split(r'===SECTION_\d+===', qual_report)
        sec1 = sections[1].strip() if len(sections) > 1 else "데이터를 파싱할 수 없습니다. (전체 요약 탭을 확인하세요)"
        sec2 = sections[2].strip() if len(sections) > 2 else "데이터를 파싱할 수 없습니다."
        sec3 = sections[3].strip() if len(sections) > 3 else "데이터를 파싱할 수 없습니다."
        sec4 = sections[4].strip() if len(sections) > 4 else qual_report # Fallback to full report if parsing fails completely
        
        with t_b1:
            st.markdown("### 1. 상위 및 관련계획")
            st.markdown(sec1)
        with t_b2:
            st.markdown("### 2. 인접 시·군 공간구조")
            st.markdown(sec2)
        with t_b3:
            st.markdown("### 3. 지역현안사항")
            st.markdown(sec3)
        with t_b4:
            st.markdown("### 📝 정성적 파일 현황 분석 종합")
            st.markdown(sec4)

elif main_tab == "C. 최종 종합 구상":
    if not st.session_state.get('analysis_done_C'):
         st.info("C단계 최종 종합 분석을 먼저 실행해 주세요. (A, B단계 선행 필수)")
    else:
        t_c1, t_c2 = st.tabs(["총괄보고서", "구상도"])
        with t_c1:
            st.markdown("### 🏛️ [C] 최종 종합 도출 보고서")
            st.markdown(st.session_state['generated_report'])
            
            st.download_button("📥 마크다운(.md) 보고서 다운로드", 
                               data=st.session_state['generated_report'], 
                               file_name=f"{st.session_state['result_sido']}_미래공간구조_종합구상안.md", 
                               mime="text/markdown")
        with t_c2:
            st.markdown("**(차후 업데이트 예정)** AI 기반 구상도 자동 생성/시각화 영역")

# ==========================================
# 4. AI 개발 어시스턴트 통합
# ==========================================
st.markdown("<br><br>", unsafe_allow_html=True)
st.markdown("---")
with st.expander("💬 AI 개발 어시스턴트", expanded=False):
    if not GEMINI_API_KEY or GEMINI_API_KEY.strip() == "":
        st.warning("상단 설정에 Gemini API 키를 입력하세요.")
    else:
        if "messages" not in st.session_state:
            st.session_state.messages = [{"role": "assistant", "content": "안녕하세요! 궁금한 점이 있으면 물어보세요."}]
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]): st.markdown(msg["content"])
        if prompt := st.chat_input("질문을 입력하세요..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"): st.markdown(prompt)
            with st.chat_message("assistant"):
                history = st.session_state.messages[:-1]
                try:
                    response_text = get_gemini_response(prompt, history, GEMINI_API_KEY)
                    st.markdown(response_text)
                    st.session_state.messages.append({"role": "assistant", "content": response_text})
                except GeminiAPIError as e:
                    st.error('서버 응답이 지연되었습니다. 잠시 후 다시 시도해 주세요.')
                    st.session_state.messages.append({"role": "assistant", "content": "오류: 서버 통신 실패"})