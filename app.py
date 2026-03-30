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

# ===== 폰트 로드 (가장 확실한 방식: 파일 경로 직접 지정) =====
_APP_DIR = os.path.dirname(os.path.abspath(__file__))

# 1) @@폰트 폴더의 폰트를 작업 디렉토리로 복사 (한 번만 실행)
_local_font = os.path.join(_APP_DIR, 'NanumGothic.ttf')
_source_font = os.path.join(_APP_DIR, '@@폰트', 'NanumGothic.ttf')
if not os.path.exists(_local_font) and os.path.exists(_source_font):
    import shutil
    shutil.copy2(_source_font, _local_font)

# 2) 폰트 파일 경로 결정
custom_font_path = None
for _fp in [_local_font, _source_font, 'C:/Windows/Fonts/malgun.ttf']:
    if os.path.exists(_fp):
        custom_font_path = _fp
        break

# 3) 폰트 적용 - fname 매개변수로 직접 지정 (쿠시 무시)
if custom_font_path:
    fm.fontManager.addfont(custom_font_path)
    custom_fontprops = fm.FontProperties(fname=custom_font_path)
    plt.rcParams['font.family'] = custom_fontprops.get_name()
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
    
    TEXT_LIMIT = 400000
    
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
        TEXT_LIMIT = 400000
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
    
    st.markdown("### 📁 공간구조 진단 및 구상 참고 자료 업로드")
    
    # 텍스트 추출 한도 (유료 API 활용, 40만 자)
    TEXT_LIMIT = 400000
    
    st.markdown("**1. 상위계획**")
    uploaded_plan_files = st.file_uploader("상위계획 문서 업로드 (PDF, TXT)", type=['pdf', 'txt'], accept_multiple_files=True, key="upload_plan")
    
    if uploaded_plan_files:
        plan_extracted = extract_text_from_upload_cached(uploaded_plan_files, "plan_text_cache")
        if len(plan_extracted) > TEXT_LIMIT:
            st.warning('문서 용량이 40만 자를 초과합니다. 40만 자까지만 분석됩니다.')
    
    st.markdown("**2. 인접지자체 도시·군기본계획**")
    uploaded_adj_files = st.file_uploader("인접지자체 계획 문서 업로드 (PDF, TXT)", type=['pdf', 'txt'], accept_multiple_files=True, key="upload_adj")
    
    if uploaded_adj_files:
        adj_extracted = extract_text_from_upload_cached(uploaded_adj_files, "adj_text_cache")
        if len(adj_extracted) > TEXT_LIMIT:
             st.warning('문서 용량이 40만 자를 초과합니다. 40만 자까지만 분석됩니다.')
             
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
        spatial_data_status.success(f"{len(uploaded_spatial_files)}개의 공간 파일이 업로드되었습니다. 진단 분석 시 행정동과 자동 교차 분석됩니다.")
            
    st.markdown("**4. 법정 지침 (도시·군기본계획수립지침)**")
    uploaded_guide_files = st.file_uploader("법정 지침 문서 (PDF, TXT) - 미업로드 시 서버 기본 지침 적용", type=['pdf', 'txt'], accept_multiple_files=True, key="upload_guide")
    
    if uploaded_guide_files:
        guide_extracted = extract_text_from_upload_cached(uploaded_guide_files, "guide_text_cache")
        if len(guide_extracted) > TEXT_LIMIT:
             st.warning('문서 용량이 40만 자를 초과합니다. 40만 자까지만 분석됩니다.')

    st.markdown("**5. 토지적성평가 결과 (2-B 대안설정용)**")
    uploaded_land_aptitude = st.file_uploader("토지적성평가 문서/데이터 업로드 (PDF, TXT)", type=['pdf', 'txt'], accept_multiple_files=True, key="upload_land")
    
    if uploaded_land_aptitude:
        land_extracted = extract_text_from_upload_cached(uploaded_land_aptitude, "land_text_cache")
        if len(land_extracted) > TEXT_LIMIT:
             st.warning('문서 용량이 40만 자를 초과합니다. 40만 자까지만 분석됩니다.')

    st.markdown("---")

# (이 아래부터는 기존의 SIDO_MAP 등 원래 코드가 그대로 이어지면 됩니다!)

SIDO_MAP = {
    "서울특별시": "11", "부산광역시": "21", "대구광역시": "22", "인천광역시": "23",
    "광주광역시": "24", "대전광역시": "25", "울산광역시": "26", "세종특별자치시": "29",
    "경기도": "31", "강원특별자치도": "32", "충청북도": "33", "충청남도": "34",
    "전북특별자치도": "35", "전라남도": "36", "경상북도": "37", "경상남도": "38",
    "제주특별자치도": "39"
}

# 인접 시도 매핑 (시가지 변화 지도에서 주변 시군구 표시용)
ADJACENT_SIDO_MAP = {
    "11": ["31", "23"],                          # 서울 ↔ 경기, 인천
    "21": ["38", "26"],                          # 부산 ↔ 경남, 울산
    "22": ["37", "38"],                          # 대구 ↔ 경북, 경남
    "23": ["31", "11"],                          # 인천 ↔ 경기, 서울
    "24": ["36"],                                 # 광주 ↔ 전남
    "25": ["33", "34", "29"],                    # 대전 ↔ 충북, 충남, 세종
    "26": ["38", "21", "37"],                    # 울산 ↔ 경남, 부산, 경북
    "29": ["34", "33", "25"],                    # 세종 ↔ 충남, 충북, 대전
    "31": ["11", "23", "32", "33", "34"],        # 경기 ↔ 서울, 인천, 강원, 충북, 충남
    "32": ["31", "33", "37"],                    # 강원 ↔ 경기, 충북, 경북
    "33": ["31", "32", "25", "29", "34", "37", "35"],  # 충북
    "34": ["31", "29", "25", "33", "35", "36"],  # 충남
    "35": ["33", "34", "36", "38"],              # 전북
    "36": ["24", "34", "35", "38"],              # 전남
    "37": ["32", "33", "22", "38", "26"],        # 경북
    "38": ["21", "26", "22", "37", "35", "36"],  # 경남
    "39": [],                                     # 제주 (인접 없음)
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
                   next((m for m in valid_models if '2.5-flash' in m.lower()), valid_models[0]))
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
            res = requests.post(url, json=payload, headers=headers, timeout=300)
            if res.status_code == 200:
                return res.json()['candidates'][0]['content']['parts'][0]['text']
            elif res.status_code == 429: # Too Many Requests (Rate Limit)
                if attempt < retries - 1:
                    time.sleep(10 * (attempt + 1)) # API 할당량 초기화를 위해 10초, 20초 후 재시도
                    continue
                else:
                    raise GeminiAPIError("Too Many Requests (Rate Limit - API 요청 속도 한도 초과)")
            else:
                if attempt < retries - 1:
                    time.sleep(5)
                    continue
                # 에러 메시지 상세화
                error_detail = ""
                try:
                    error_detail = res.json()
                except:
                    error_detail = res.text
                raise GeminiAPIError(f"HTTP Error: {res.status_code} - {error_detail}")
        except Exception as e:
            if isinstance(e, GeminiAPIError):
                raise e
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
        # 인구 데이터
        pop_url = "https://sgisapi.kostat.go.kr/OpenAPI3/stats/searchpopulation.json"
        pop_res = safe_req(pop_url, {"year": str(year), "adm_cd": str(gu), "low_search": "1", "accessToken": token})
        err_cd = pop_res.get("errCd", -1)
        if err_cd == 0 or str(err_cd) == "0":
            for item in pop_res.get("result", []):
                acd = str(item.get("adm_cd", "")).strip()
                pop_dict[acd] = safe_int(item.get("tot_ppltn", item.get("population", 0)))
        
        # 사업체/종사자 데이터 (최신 연도 부재 시 이전 연도 자동 폴백)
        biz_url = "https://sgisapi.kostat.go.kr/OpenAPI3/stats/company.json"
        biz_found = False
        for try_year in [int(year), int(year)-1, int(year)-2]:
            biz_res = safe_req(biz_url, {"year": str(try_year), "adm_cd": str(gu), "low_search": "1", "accessToken": token})
            err_cd_b = biz_res.get("errCd", -1)
            if err_cd_b == 0 or str(err_cd_b) == "0":
                result_items = biz_res.get("result", [])
                if result_items:
                    # 'N/A' 값 체크 - 모든 값이 N/A면 다음 연도로
                    sample_val = str(result_items[0].get("corp_cnt", "N/A"))
                    if sample_val == "N/A":
                        continue  # 이 연도는 데이터 미공개, 다음 연도 시도
                    for item in result_items:
                        acd = str(item.get("adm_cd", "")).strip()
                        biz_dict[acd] = safe_int(item.get("corp_cnt", 0))
                        worker_dict[acd] = safe_int(item.get("tot_worker", item.get("employee", 0)))
                    biz_found = True
                    break
    
    # 디버깅: 데이터 수집 실패 시 st.warning으로 표시
    import streamlit as _st_debug
    if not pop_dict:
        _st_debug.warning(f"⚠️ 인구 데이터 수집 실패 (parent_codes: {list(parent_codes)}, year: {year})")
    if not biz_dict:
        _st_debug.warning(f"⚠️ 사업체 데이터 수집 실패 - {year}년 및 이전 2개년 데이터 부재")
    
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
        parts = [df for df in [df1, df2, df3, df4] if not df.empty]
        return pd.concat(parts, ignore_index=True) if parts else gpd.GeoDataFrame()
    return gdf

@st.cache_data(show_spinner=False)
def get_its_road_data(year_str, sido_geom_wkt, cache_code):
    import os, glob
    import geopandas as gpd
    from shapely import wkt
    base_dir = r"c:\Users\user\Desktop\ai\_교통네트워크(연도별)"
    if not os.path.exists(base_dir): return None
    cache_dir = os.path.join(base_dir, "cache")
    if not os.path.exists(cache_dir): os.makedirs(cache_dir, exist_ok=True)
    
    cache_path = os.path.join(cache_dir, f"cache_{cache_code}_{year_str}.shp")
    if os.path.exists(cache_path):
        try: return gpd.read_file(cache_path)
        except: pass
        
    pattern = os.path.join(base_dir, f"[{year_str}*]NODELINKDATA", "MOCT_LINK.shp")
    matches = glob.glob(pattern)
    if not matches: return None
    
    sido_geom = wkt.loads(sido_geom_wkt)
    temp_gdf = gpd.GeoDataFrame(geometry=[sido_geom], crs=5179).to_crs(epsg=5181)
    tb = temp_gdf.total_bounds
    
    try:
        gdf = gpd.read_file(matches[0], bbox=tuple(tb))
        if gdf.empty: return None
        gdf = gdf.to_crs(epsg=5179)
        gdf = gpd.clip(gdf, sido_geom)
        gdf.to_file(cache_path, encoding='utf-8')
        return gdf
    except:
        return None

def get_vworld_road_bbox(minx, miny, maxx, maxy, key, depth=0):
    url = "https://api.vworld.kr/req/data"
    bbox_str = f"BOX({minx},{miny},{maxx},{maxy})"
    target_codes = ['RDD001', 'RDD002', 'RDD003', 'RDD004', 'RDD005']
    all_features = []
    
    for code in target_codes:
        params = {
            "service": "data", "request": "GetFeature", "data": "lt_l_n3a0020000",
            "key": key, "domain": "http://localhost", "crs": "EPSG:3857",
            "geomFilter": bbox_str, "size": 1000, "attrFilter": f"rddv:=:{code}"
        }
        res = safe_req(url, params)
        if res and "response" in res and "result" in res["response"]:
            fc = res["response"]["result"].get("featureCollection", {})
            features = fc.get("features", [])
            all_features.extend(features)
            
    if not all_features:
        return gpd.GeoDataFrame()
        
    gdf = gpd.GeoDataFrame.from_features(all_features)
    gdf.set_crs(epsg=3857, inplace=True)
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
        selected_sido = st.selectbox("• 시도 선택", ["선택"] + list(SIDO_MAP.keys()), index=0)
        sido_code = SIDO_MAP.get(selected_sido, "")
        if sido_code:
            sigungu_dict = get_cached_sigungu_list(sido_code)
            sigungu_options = ["선택"] + list(sigungu_dict.keys())
        else:
            sigungu_dict = {}
            sigungu_options = ["선택"]
        selected_sigungu_name = st.selectbox("• 시군구 선택", sigungu_options, index=0)
    with hc2:
        target_year = st.selectbox("• 기준년도", ["선택", "2025", "2024", "2023", "2022", "2021", "2020"], index=0)
        future_year = st.selectbox("• 목표년도", ["선택", "2040", "2035", "2030", "2045", "2050"], index=0)

st.markdown("<hr style='border: 1px solid #4A7CB6;'>", unsafe_allow_html=True)

if selected_sido == "선택" or selected_sigungu_name == "선택" or target_year == "선택" or future_year == "선택":
    st.info("👆 우측 상단에서 **분석범위(시도, 시군구, 기준/목표년도)를 모두 선택**해야 분석 내용이 표시됩니다.")
    st.stop()

if 'analysis_done_A' not in st.session_state: st.session_state['analysis_done_A'] = False
if 'analysis_done_B' not in st.session_state: st.session_state['analysis_done_B'] = False
if 'analysis_done_C' not in st.session_state: st.session_state['analysis_done_C'] = False


chap1_tab, chap2_tab = st.tabs(["📂 1. 공간구조의 진단", "📂 2. 공간구조 개편방향"])

with chap1_tab:
    # 총괄 분석 버튼
    btn_all = st.button("🚀 1. 공간구조 진단 총괄 분석", key="btn_all_chap1", use_container_width=True, type="primary")
    if btn_all:
        st.session_state['run_all_chap1'] = True
        st.session_state['run_all_step'] = 1
    
    st.markdown("### 1-A. 기존 공간구조의 문제점 진단")
    st.markdown("#### (1) 최신 도시계획 및 공간 트렌드 분석")
    run_all = st.session_state.get('run_all_chap1', False)
    if run_all:
        with st.spinner("최신 메가트렌드를 분석 중입니다..."):
            trend_prompt = f"""[{selected_sido} {selected_sigungu_name}]의 뉴노멀, 인구감소, 지방소멸, 탄소중립, 기후변화 등 여건 변화에 따른 공간 트렌드를 분석해 줘.
반드시 다음 형태와 규칙을 엄격히 지켜서 작성해:

[출력 형식 예시]
**1. 첫번째 카테고리 소제목**
- 첫번째 세부내용 (강화, 확대, 필요 등 단어로 종결, 상세하고 풍부하게 작성...)
- 두번째 세부내용 (상세하고 풍부하게 작성...)
- 세번째 세부내용 (상세하고 풍부하게 작성...)

**2. 두번째 카테고리 소제목**
- 첫번째 세부내용
...

[상세 지시사항]
1. 위 출력 형식처럼 전체를 3가지 주요 카테고리로 나누고, 각 카테고리 제목(소제목)은 헤딩(###, #### 등) 태그를 쓰면 아래 줄과의 간격이 너무 벌어지므로 절대로 헤딩을 쓰지 말고 숫자와 볼드체(**)만 사용하여 '**1. 소제목**' 형태로 표시할 것.
2. 하위 세부 내용은 반드시 '-' 기호를 사용한 글머리 기호(bullet point)로 3개씩 작성할 것.
3. [분량 지정] 각 세부 내용(꼭지)은 한 줄로 짧게 끝나지 않도록, A4 용지로 출력했을 때 2줄 이상(약 80~120자 내외)이 될 만큼 구체적인 근거나 방향성을 담아 길고 상세하게 서술할 것.
4. [어투 지정] 세부 내용의 끝맺음은 '~합니다', '~임', '~함' 등의 서술어 종결이 아니라, 반드시 '~확충', '~마련', '~필요', '~강화', '~도입'과 같이 핵심적인 '단어(명사)' 자체로 딱 떨어지게 마칠 것.
5. 카테고리 소제목과 그 바로 첫번째 세부내용 사이에는 절대로 빈 줄(Enter)을 넣지 말 것. 반면, 서로 다른 카테고리 묶음 사이에는 빈 줄을 하나 넣어 확실히 구분할 것.
6. 인사말, 맺음말 등 불필요한 서두 구문은 일절 출력하지 말고 곧바로 '**1. 카테고리 소제목**'부터 시작할 것.
"""
            try:
                st.session_state['trend_report'] = get_gemini_response(trend_prompt, [], GEMINI_API_KEY, model_override="gemini-2.5-flash")
            except Exception as e:
                st.error(str(e))
    if 'trend_report' in st.session_state:
        st.info(st.session_state['trend_report'])

    st.markdown("#### (2) 시가지면적 및 교통축 변화추이")
    if run_all:
        with st.spinner("SGIS에서 과거부터 현재까지 시가지 경계를 순차적으로 수집하는 중입니다 (약 15~30초 소요)..."):
            try:
                sgis_token = get_sgis_token()
                if not sgis_token:
                    st.error("SGIS API 토큰을 가져올 수 없습니다. 설정(SGIS_KEY)을 확인하세요.")
                else:
                    progress_bar = st.progress(10, text="행정구역 데이터 로드 중...")
                    
                    # 1. 대상 시군구 행정동 경계 먼저 수집
                    target_codes = sigungu_dict[selected_sigungu_name]
                    target_gdf = get_sgis_dong(target_codes, target_year, sgis_token)
                    
                    # 2. 같은 시도 내 시군구 코드 수집
                    all_sido_codes = []
                    for k, v in sigungu_dict.items():
                        if k != "전체":
                            all_sido_codes.extend(v)
                    
                    # 3. ★ 인접 시도의 시군구 코드도 추가 수집
                    adj_sido_codes_list = ADJACENT_SIDO_MAP.get(sido_code, [])
                    adj_extra_codes = []
                    for adj_sido_cd in adj_sido_codes_list:
                        adj_sigungu = get_cached_sigungu_list(adj_sido_cd)
                        for k, v in adj_sigungu.items():
                            if k != "전체":
                                adj_extra_codes.extend(v)
                    
                    # 같은 시도 + 인접 시도 모든 시군구 코드
                    all_display_codes = all_sido_codes + adj_extra_codes
                            
                    sido_gdf = get_sgis_dong(all_display_codes, target_year, sgis_token)
                    
                    if not target_gdf.empty and not sido_gdf.empty:
                        # 읍면동 경계를 시·군·구 단위로 병합 (지저분한 내부 행정동 선 제거)
                        try:
                            sido_gdf['sigungu_cd'] = sido_gdf['adm_cd'].str[:5]
                            sido_sigungu_gdf = sido_gdf.dissolve(by='sigungu_cd')
                        except:
                            sido_sigungu_gdf = sido_gdf
                            
                        target_geom = target_gdf.geometry.unary_union
                        
                        # 4. ★ 행정경계가 맞닿아 있는(touches/intersects) 시군구만 필터링
                        target_geom_buffered = target_geom.buffer(100)  # 100m 여유 (경계 미세 오차 보정)
                        adj_mask = sido_sigungu_gdf.geometry.intersects(target_geom_buffered)
                        adj_sigungu_gdf = sido_sigungu_gdf[adj_mask]
                        
                        # 대상지 자체를 제외한 인접 시군구 geometry
                        adj_all_geom = adj_sigungu_gdf.geometry.unary_union
                        adj_geom = adj_all_geom.difference(target_geom)
                        
                        # 지도 배경용 전체 범위 (인접 시군구만 포함)
                        sido_sigungu_gdf = adj_sigungu_gdf
                        sido_geom = sido_sigungu_gdf.geometry.unary_union
                        
                        start_year = 2015
                        end_year = min(int(target_year), 2024)
                        years_list = list(range(start_year, end_year + 1))
                        n_years = len(years_list)
                        
                        def fetch_urban(u_type, year_str):
                            url = "https://sgisapi.kostat.go.kr/OpenAPI3/urban/boundary.geojson"
                            res = safe_req(url, {"accessToken": sgis_token, "base_year": year_str, "urban_type": u_type})
                            if res and "features" in res and res["features"]:
                                gdf = gpd.GeoDataFrame.from_features(res["features"])
                                gdf.set_crs(epsg=5179, inplace=True)
                                return gdf
                            return gpd.GeoDataFrame()
                        
                        urban_data = {}
                        
                        for i, y in enumerate(years_list):
                            y_str = str(y)
                            progress_bar.progress(10 + int((i/n_years)*80), text=f"{y_str}년 시가지 경계 및 변화 수집 중... ({i+1}/{n_years})")
                            u1 = fetch_urban("01", y_str)
                            u2 = fetch_urban("02", y_str)
                            urban_data[y_str] = (u1, u2)
                        
                        progress_bar.progress(90, text="주요 교통축(도로망) 데이터 수집 중...")
                        temp_gdf = gpd.GeoDataFrame(geometry=[sido_geom], crs=5179).to_crs(epsg=3857)
                        tb = temp_gdf.total_bounds
                        road_gdf = get_vworld_road_bbox(tb[0], tb[1], tb[2], tb[3], VWORLD_KEY)
                        if not road_gdf.empty:
                            road_gdf = road_gdf.to_crs(epsg=5179)
                            road_gdf = gpd.clip(road_gdf, sido_geom)
                            st.session_state['urban_road_gdf'] = road_gdf
                        else:
                            st.session_state['urban_road_gdf'] = gpd.GeoDataFrame()
                            
                        progress_bar.progress(95, text="데이터 수집 완료! AI가 시계열 확장 변화 분석을 수행 중입니다...")
                        
                        ai_data_str = "연도 | 대상지 도시 면적 | 대상지 준도시 면적 | 총 면적\n"
                        ai_data_str += "-" * 50 + "\n"
                        for y in years_list:
                            y_str = str(y)
                            u1, u2 = urban_data[y_str]
                            a1 = gpd.clip(u1, target_geom).geometry.area.sum()/1e6 if not u1.empty else 0
                            a2 = gpd.clip(u2, target_geom).geometry.area.sum()/1e6 if not u2.empty else 0
                            ai_data_str += f"{y_str} | {a1:.1f} ㎢ | {a2:.1f} ㎢ | {a1+a2:.1f} ㎢\n"
                            
                        prompt = f"""[{selected_sido} {selected_sigungu_name}]의 2015년부터 {end_year}년까지 연도별 대상지 시가지 면적 데이터입니다.

{ai_data_str}

위의 연속적인 시계열 양적 변화 추이를 바탕으로, 이 지역의 중심지 구조 변화와 도시성장형태(확산/축소/정체)를 종합적으로 분석해 줘.
반드시 다음 형태와 규칙을 엄격히 지켜서 작성해:

[출력 형식 예시]
**1. 첫번째 카테고리 소제목**
- 첫번째 세부내용 (강화, 확대, 필요 등 단어로 종결, 상세하고 풍부하게 작성...)
- 두번째 세부내용 (상세하고 풍부하게 작성...)
- 세번째 세부내용 (상세하고 풍부하게 작성...)

**2. 두번째 카테고리 소제목**
- 첫번째 세부내용
...

[상세 지시사항]
1. 위 출력 형식처럼 전체를 3가지 주요 카테고리로 나누고, 각 카테고리 제목(소제목)은 헤딩(###, #### 등) 태그를 쓰면 아래 줄과의 간격이 너무 벌어지므로 절대로 헤딩을 쓰지 말고 숫자와 볼드체(**)만 사용하여 '**1. 소제목**' 형태로 표시할 것.
2. 하위 세부 내용은 반드시 '-' 기호를 사용한 글머리 기호(bullet point)로 3개씩 작성할 것.
3. [분량 지정] 각 세부 내용(꼭지)은 한 줄로 짧게 끝나지 않도록, A4 용지로 출력했을 때 2줄 이상(약 80~120자 내외)이 될 만큼 구체적인 근거나 방향성을 담아 길고 상세하게 서술할 것.
4. [어투 지정] 세부 내용의 끝맺음은 '~합니다', '~임', '~함' 등의 서술어 종결이 아니라, 반드시 '~확충', '~마련', '~필요', '~강화', '~도입'과 같이 핵심적인 '단어(명사)' 자체로 딱 떨어지게 마칠 것.
5. 카테고리 소제목과 그 바로 첫번째 세부내용 사이에는 절대로 빈 줄(Enter)을 넣지 말 것. 반면, 서로 다른 카테고리 묶음 사이에는 빈 줄을 하나 넣어 확실히 구분할 것.
6. 인사말, 맺음말, '핵심 시사점', '도출해 드리겠습니다' 등 불필요한 서두/맺음 구문은 일절 출력하지 말고 곧바로 '**1. 카테고리 소제목**'부터 시작할 것.
7. [분석 중점] 중심지 구조의 공간적 분포 변화, 도시성장형태(확산형/정체형/축소형) 판단 근거, 인접 시·군과의 연담화 가능성을 핵심적으로 다룰 것.
"""
                        
                        try:
                            ai_insight = get_gemini_response(prompt, [], GEMINI_API_KEY, model_override="gemini-2.5-flash")
                        except Exception as e:
                            ai_insight = f"AI 분석 중 오류 발생: {str(e)}"
                        
                        # Session state에 시계열 데이터 모두 저장
                        st.session_state['urban_data_loaded'] = True
                        st.session_state['urban_years'] = years_list
                        st.session_state['urban_data'] = urban_data
                        st.session_state['urban_sido_sigungu_gdf'] = sido_sigungu_gdf
                        st.session_state['urban_target_gdf'] = target_gdf
                        st.session_state['urban_target_geom'] = target_geom
                        st.session_state['urban_adj_geom'] = adj_geom
                        st.session_state['urban_ai_insight'] = ai_insight
                        
                        progress_bar.empty()
                        
                    else:
                        st.warning("행정동 경계를 불러오지 못해 시가지면적을 추출할 수 없습니다.")
                        if 'progress_bar' in locals(): progress_bar.empty()
                        
            except Exception as e:
                st.error(f"분석 중 오류가 발생했습니다: {str(e)}")
                if 'progress_bar' in locals(): progress_bar.empty()

    if st.session_state.get('urban_data_loaded'):
        years_list = st.session_state['urban_years']
        urban_data = st.session_state['urban_data']
        sido_sigungu_gdf = st.session_state['urban_sido_sigungu_gdf']
        target_gdf = st.session_state['urban_target_gdf']
        target_geom = st.session_state['urban_target_geom']
        adj_geom = st.session_state['urban_adj_geom']
        
        # 좌우 레이아웃: 왼쪽 AI텍스트, 오른쪽 지도+슬라이더
        urban_col1, urban_col2 = st.columns([1.5, 1])
        
        with urban_col2:
            selected_year_str = st.select_slider("연도 슬라이더를 움직여 시간적 변화를 확인하세요:", 
                                                options=[str(y) for y in years_list], 
                                                value=str(years_list[-1]),
                                                key="urban_year_slider")
        
        u1, u2 = urban_data[selected_year_str]
        
        fig, ax = plt.subplots(figsize=(10, 10))
        minx, miny, maxx, maxy = target_geom.bounds
        margin = max(maxx - minx, maxy - miny) * 0.8
        
        sido_sigungu_gdf.plot(ax=ax, color='#f5f5f5', edgecolor='#bbbbbb', linewidth=1.0)
        target_gdf.plot(ax=ax, color='white', edgecolor='black', linewidth=1.5)
        
        if not u1.empty:
            u1_adj = gpd.clip(u1, adj_geom)
            u1_target = gpd.clip(u1, target_geom)
            if not u1_adj.empty: u1_adj.plot(ax=ax, color='red', alpha=0.15)
            if not u1_target.empty: u1_target.plot(ax=ax, color='red', alpha=0.6)
                
        if not u2.empty:
            u2_adj = gpd.clip(u2, adj_geom)
            u2_target = gpd.clip(u2, target_geom)
            if not u2_adj.empty: u2_adj.plot(ax=ax, color='orange', alpha=0.15)
            if not u2_target.empty: u2_target.plot(ax=ax, color='orange', alpha=0.6)
                
        # --- Road Overlay ---
        import os
        road_gdf = None
        sido_geom = sido_sigungu_gdf.geometry.unary_union
        road_source_msg = ""
        with st.spinner(f"ITS {selected_year_str}년 도로망 데이터 확인 및 추출 중..."):
            cache_code = f"{selected_sido}_{selected_sigungu_name}"
            road_gdf = get_its_road_data(selected_year_str, sido_geom.wkt, cache_code)
        if road_gdf is not None:
            road_source_msg = f"✅ **도로망:** {selected_year_str}년도 ITS 파일 적용"
        elif road_gdf is None and 'urban_road_gdf' in st.session_state:
            road_gdf = st.session_state['urban_road_gdf']
            road_source_msg = f"⚠️ **도로망:** {selected_year_str}년도 파일 누락 ➔ 기본(VWorld)망 대체"
            
        if road_gdf is not None and not road_gdf.empty:
            r_col = 'ROAD_RANK' if 'ROAD_RANK' in road_gdf.columns else ('rddv' if 'rddv' in road_gdf.columns else None)
            if r_col == 'ROAD_RANK':
                wide_road = road_gdf[road_gdf[r_col].astype(str).isin(['101', '102', '103', '104'])]
                reg_road = road_gdf[road_gdf[r_col].astype(str).isin(['105', '106', '107'])]
            elif r_col == 'rddv':
                wide_road = road_gdf[road_gdf[r_col].astype(str).isin(['RDD001', 'RDD002', 'RDD003'])]
                reg_road = road_gdf[road_gdf[r_col].astype(str).isin(['RDD004', 'RDD005'])]
            else:
                wide_road, reg_road = gpd.GeoDataFrame(), gpd.GeoDataFrame()
            if not wide_road.empty: wide_road.plot(ax=ax, color='#004488', linewidth=2.5, zorder=5)
            if not reg_road.empty: reg_road.plot(ax=ax, color='#5588cc', linewidth=1.2, zorder=4, linestyle='--')
                
        ax.set_title(f"{selected_year_str}년 시가지(도시·준도시) 분포 현황", fontproperties=custom_fontprops, fontsize=16)
        ax.axis('off')
        ax.set_xlim(minx - margin, maxx + margin)
        ax.set_ylim(miny - margin, maxy + margin)
        
        import matplotlib.patches as mpatches
        import matplotlib.lines as mlines
        legend_elements = [
            mpatches.Patch(color='red', alpha=0.6, label='대상 시·군 도시'),
            mpatches.Patch(color='orange', alpha=0.6, label='대상 시·군 준도시'),
            mpatches.Patch(color='red', alpha=0.15, label='인접 지역 도시'),
            mpatches.Patch(color='orange', alpha=0.15, label='인접 지역 준도시'),
            mlines.Line2D([0], [0], color='#004488', lw=2.5, label='광역교통축 (고속/국도/광역시도)'),
            mlines.Line2D([0], [0], color='#5588cc', lw=1.2, linestyle='--', label='지역간선교통축 (지방도/시도)')
        ]
        fig.legend(handles=legend_elements, prop=custom_fontprops, loc='lower center', ncol=3, bbox_to_anchor=(0.5, 0.02))
        plt.tight_layout(rect=[0, 0.12, 1, 0.95])
        
        with urban_col1:
            st.success(st.session_state['urban_ai_insight'])
        with urban_col2:
            st.pyplot(fig)
            if road_source_msg:
                st.caption(road_source_msg)


    # --- Step A: 정량 분석 ---
    st.markdown("#### (3) 인구, 산업, 토지이용 분포 현황 분석")



    weights_map = {"인구(명)": 1.0, "사업체(수)": 1.0, "종사자(수)": 1.0, "중심상업(%)": 1.0, "일반상업(%)": 1.0, "근린상업(%)": 1.0, "준주거(%)": 1.0}

    if run_all:
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
        _zoning_fail_count = 0
        for idx, row in dong_3857.iterrows():
            b = row.geometry.bounds 
            zdf = get_vworld_zoning_bbox(b[0], b[1], b[2], b[3], VWORLD_KEY)
            if not zdf.empty:
                zoning_list.append(zdf)
            else:
                _zoning_fail_count += 1
            time.sleep(0.3)  # VWorld API 속도 제한 방지
        
        if _zoning_fail_count > 0:
            st.warning(f"⚠️ 용도지역 수집: {len(dong_3857)}개 행정동 중 {_zoning_fail_count}개 응답 없음 (VWorld API 제한 또는 데이터 부재)")

        zoning_gdf = pd.concat(zoning_list, ignore_index=True) if zoning_list else gpd.GeoDataFrame()
        
        # ★ 디버그: 수집 결과 표시
        st.caption(f"📋 [디버그] 용도지역 수집 결과: {len(zoning_list)}개 동에서 총 {len(zoning_gdf)}개 피처")
        
        target_mapping = {'UQA210': '중심상업', 'UQA220': '일반상업', 'UQA230': '근린상업', 'UQA130': '준주거'}
        if not zoning_gdf.empty:
            code_col = 'ucode' if 'ucode' in zoning_gdf.columns else None
            if code_col is None:
                for c in zoning_gdf.columns:
                    if 'code' in c.lower() or 'cde' in c.lower():
                        code_col = c
                        break
            if code_col is None:
                st.error(f"⚠️ 용도지역 코드 컬럼을 찾을 수 없습니다. 컬럼: {list(zoning_gdf.columns)}")
                code_col = zoning_gdf.columns[0]  # fallback
            
            unique_codes = zoning_gdf[code_col].unique()
            st.caption(f"📋 [디버그] 코드컬럼={code_col}, 고유코드={list(unique_codes)[:15]}")
            
            before_filter = len(zoning_gdf)
            zoning_gdf = zoning_gdf[zoning_gdf[code_col].isin(target_mapping.keys())]
            st.caption(f"📋 [디버그] 필터 후: {before_filter} → {len(zoning_gdf)}개 (대상코드: {list(target_mapping.keys())})")
            
            if not zoning_gdf.empty:
                zoning_gdf['target_zone'] = zoning_gdf[code_col].map(target_mapping)
                zoning_gdf['geom_wkt'] = zoning_gdf.geometry.to_wkt()
                zoning_gdf = zoning_gdf.drop_duplicates(subset=['geom_wkt']).drop(columns=['geom_wkt'])

        my_bar.progress(80, text="[3/4] 공간 연산 중...")
        if not zoning_gdf.empty:
            zoning_gdf = zoning_gdf.to_crs(epsg=5179)
        dong_gdf['geometry'] = dong_gdf.geometry.buffer(0)
        if not zoning_gdf.empty: zoning_gdf['geometry'] = zoning_gdf.geometry.buffer(0)

        intersected = gpd.overlay(dong_gdf, zoning_gdf, how='intersection') if not zoning_gdf.empty else gpd.GeoDataFrame()
        st.caption(f"📋 [디버그] overlay 결과: {len(intersected)}개 피처")
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

        # AI 요약 분석 자동 생성
        my_bar.progress(97, text="AI가 인구·산업·토지이용 현황을 분석 중입니다...")
        raw_summary = final_df.drop(columns=["adm_cd"]).sort_values(by="인구(명)", ascending=False).head(15).to_csv(index=False)
        quant_ai_prompt = f"""[{selected_sido} {selected_sigungu_name}]의 행정동별 인구, 산업(사업체·종사자), 토지이용(용도지역) 현황 데이터입니다.

{raw_summary}

위 데이터를 바탕으로 이 지역의 인구·산업·토지이용 분포 특성과 중심지 구조를 종합적으로 분석해 줘.
반드시 다음 형태와 규칙을 엄격히 지켜서 작성해:

[출력 형식 예시]
**1. 첫번째 카테고리 소제목**
- 첫번째 세부내용 (강화, 확대, 필요 등 단어로 종결, 상세하고 풍부하게 작성...)
- 두번째 세부내용 (상세하고 풍부하게 작성...)
- 세번째 세부내용 (상세하고 풍부하게 작성...)

**2. 두번째 카테고리 소제목**
- 첫번째 세부내용
...

[상세 지시사항]
1. 전체를 3가지 주요 카테고리로 나누고, 소제목은 '**1. 소제목**' 형태(볼드체+번호)로 표시. 마크다운 헤딩(###, ####) 절대 금지.
2. 하위 세부 내용은 '-' 글머리 기호로 3개씩 작성.
3. [분량] 각 세부 내용은 A4 2줄 이상(약 80~120자), 구체적 행정동명과 수치를 적극 인용.
4. [어투] '~확충', '~마련', '~필요', '~강화' 등 핵심 명사 단어로 종결.
5. 소제목과 첫 세부내용 사이 빈 줄 금지. 카테고리 간에만 빈 줄 1개.
6. 인사말/맺음말/서두 문구 일절 금지. 곧바로 '**1. 소제목**'부터 시작.
"""
        try:
            quant_ai_insight = get_gemini_response(quant_ai_prompt, [], GEMINI_API_KEY, model_override="gemini-2.5-flash")
        except:
            quant_ai_insight = "AI 분석을 불러오는 데 실패했습니다."
        st.session_state['quant_ai_insight'] = quant_ai_insight

        my_bar.progress(100, text="✨ 정량 분석 완료!")
        st.success("정량적 현황 데이터 산출이 완료되었습니다!")

    # (3) 분석 결과 표시 (좌: AI 텍스트, 우: 상단 표 + 하단 삽도)
    if st.session_state.get('analysis_done_A'):
        q_col1, q_col2 = st.columns([1.5, 1])
        with q_col1:
            if 'quant_ai_insight' in st.session_state:
                st.info(st.session_state['quant_ai_insight'])
        with q_col2:
            if 'display_norm_df' in st.session_state:
                st.markdown("**중심지 지수 상위 10개 행정동**")
                top10 = st.session_state['display_norm_df'].sort_values(by="★중심지_지수(합산)", ascending=False).head(10)[['행정동', '★중심지_지수(합산)']]
                top10.index = range(1, len(top10) + 1)
                st.dataframe(top10, use_container_width=True, height=200)
            
            # 중심지 지수 분포 삽도
            if 'dong_gdf' in st.session_state and 'norm_df' in st.session_state:
                import matplotlib.patheffects as patheffects
                dong_map = st.session_state['dong_gdf'].copy()
                norm_map = st.session_state['norm_df'][['adm_cd', '★중심지_지수(합산)']].copy()
                dong_map = dong_map.merge(norm_map, on='adm_cd', how='left')
                dong_map['★중심지_지수(합산)'] = dong_map['★중심지_지수(합산)'].fillna(0)
                
                fig_q, ax_q = plt.subplots(figsize=(8, 8))
                dong_map.plot(column='★중심지_지수(합산)', ax=ax_q, cmap='YlOrRd', 
                            edgecolor='black', linewidth=0.5, legend=True,
                            legend_kwds={'shrink': 0.6})
                # 컬러바 라벨에 한글 폰트 직접 적용
                cbar = ax_q.get_figure().axes[-1]  # 컬러바 축
                cbar.set_ylabel('중심지 지수', fontproperties=custom_fontprops, fontsize=11)
                for lbl in cbar.get_yticklabels():
                    lbl.set_fontproperties(custom_fontprops)
                
                # 행정동 라벨 표시
                for idx, row in dong_map.iterrows():
                    name_parts = str(row.get('adm_nm', '')).split()
                    label = name_parts[-1] if name_parts else ''
                    centroid = row.geometry.centroid
                    ax_q.annotate(label, xy=(centroid.x, centroid.y),
                                ha='center', va='center', fontsize=6,
                                fontproperties=custom_fontprops,
                                path_effects=[patheffects.withStroke(linewidth=1.5, foreground='white')])
                
                ax_q.set_title("중심지 지수 분포", fontproperties=custom_fontprops, fontsize=12, fontweight='bold')
                ax_q.axis('off')
                plt.tight_layout()
                st.pyplot(fig_q)

        # RAW 데이터 및 정규화 데이터 제공
        with st.expander("📊 상세 데이터 확인 (RAW / 정규화)", expanded=False):
            data_tab1, data_tab2 = st.tabs(["RAW 데이터", "정규화 데이터"])
            with data_tab1:
                if 'export_raw_df' in st.session_state:
                    st.dataframe(st.session_state['export_raw_df'], use_container_width=True)
            with data_tab2:
                if 'display_norm_df' in st.session_state:
                    st.dataframe(st.session_state['display_norm_df'], use_container_width=True)


    st.markdown("### 1-B. 기존 공간구조 문제점 분석")
    if run_all:
        with st.spinner("공간구조 문제점을 진단 중입니다..."):
            # 1-A 분석 결과들을 종합하여 프롬프트 구성
            diag_context = ""
            if 'trend_report' in st.session_state:
                diag_context += f"\n[1-A-(1) 최신 도시계획 및 공간 트렌드 분석 결과]\n{st.session_state['trend_report'][:2000]}\n"
            if 'urban_ai_insight' in st.session_state:
                diag_context += f"\n[1-A-(2) 시가지면적 및 교통축 변화추이 분석 결과]\n{st.session_state['urban_ai_insight'][:2000]}\n"
            if 'quant_ai_insight' in st.session_state:
                diag_context += f"\n[1-A-(3) 인구·산업·토지이용 분포 현황 분석 결과]\n{st.session_state['quant_ai_insight'][:2000]}\n"
            if st.session_state.get('analysis_done_A') and 'display_norm_df' in st.session_state:
                quant_data = st.session_state['display_norm_df'].head(15).to_csv(index=False)
                diag_context += f"\n[중심지 지수 상위 15개 행정동 데이터]\n{quant_data}\n"

            diag_prompt = f"""[{selected_sido} {selected_sigungu_name}]의 기존 공간구조 문제점을 종합적으로 분석해 줘.
아래 제공되는 1-A 단계 분석 결과들을 반드시 바탕으로 하여, 현재 공간구조가 지닌 핵심적인 문제점을 심층 진단해 주십시오.

{diag_context}

반드시 다음 형태와 규칙을 엄격히 지켜서 작성해:

[출력 형식 예시]
**1. 첫번째 카테고리 소제목**
- 첫번째 세부내용 (강화, 확대, 필요 등 단어로 종결, 상세하고 풍부하게 작성...)
- 두번째 세부내용 (상세하고 풍부하게 작성...)
- 세번째 세부내용 (상세하고 풍부하게 작성...)

**2. 두번째 카테고리 소제목**
- 첫번째 세부내용
...

[상세 지시사항]
1. 전체를 3가지 주요 카테고리로 나누고, 소제목은 '**1. 소제목**' 형태(볼드체+번호)로 표시. 마크다운 헤딩(###, ####) 절대 금지.
2. 하위 세부 내용은 '-' 글머리 기호로 3개씩 작성.
3. [분량] 각 세부 내용은 A4 2줄 이상(약 80~120자), 구체적 행정동명과 수치를 적극 인용하여 길고 상세하게.
4. [어투] '~확충', '~마련', '~필요', '~강화' 등 핵심 명사 단어로 종결.
5. 소제목과 첫 세부내용 사이 빈 줄 금지. 카테고리 간에만 빈 줄 1개.
6. 인사말/맺음말/서두 문구 일절 금지. 곧바로 '**1. 소제목**'부터 시작.
7. [분석 중점] 중심지 기능의 쏠림 현상, 신구 시가지 간 불균형, 취약 지역 발생, 교통축과 시가지 확산 간의 괴리 등 기존 공간구조가 가지는 구조적 문제점을 행정동명과 연계하여 서술.
"""
            try:
                st.session_state['diag_report'] = get_gemini_response(diag_prompt, [], GEMINI_API_KEY, model_override="gemini-2.5-flash")
            except Exception as e:
                st.error(str(e))
        # ★ 총괄 분석 플래그 리셋 (슬라이더 등 위젯 조작 시 재분석 방지)
        st.session_state['run_all_chap1'] = False
    if 'diag_report' in st.session_state:
        st.success(st.session_state['diag_report'])

with chap2_tab:
    st.markdown("### 2. 공간구조 개편방향 설정")
    growth_type = st.radio("도시성장형태", ["성장형", "성숙안정형", "감소형"], horizontal=True)
    st.session_state['growth_type'] = growth_type
    
    st.markdown("### 2-A. 당해 시·군 및 주변 시·군 여건 분석")


    # --- Step B: 정성 분석 ---
    bc1, bc2 = st.columns([2.5, 1])
    bc1.markdown("#### (1) 미래여건변화 분석 (정성)")
    btn_b = bc2.button("분석 시작", key="btn_b", use_container_width=True, type="primary")

    st.markdown("**분석 AI모델 & 반영사항**")
    b1, b2 = st.columns(2)
    with b1:
        st.markdown("<div style='font-size: 14px;'>분석 AI모델</div>", unsafe_allow_html=True)
        selected_ai_model_qual = st.radio("AI모델 선택", 
            ["GEMINI 3.1 Pro (최신/최고성능)", "GEMINI 2.5 Pro (안정/대용량)", "GEMINI 2.5 Flash (초고속)"], 
            index=0,
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

            if "3.1 Pro" in selected_ai_model_qual:
                model_name = "models/gemini-3.1-pro-preview"
            elif "2.5 Pro" in selected_ai_model_qual:
                model_name = "models/gemini-2.5-pro"
            else:
                model_name = "models/gemini-2.5-flash"

            try:
                result_qual = get_gemini_response(qual_prompt, [], GEMINI_API_KEY, model_override=model_name)

                st.session_state['qual_report'] = result_qual
                st.session_state['analysis_done_B'] = True
                st.success("✨ B단계 정성적 현황 분석이 완료되었습니다!")
            except GeminiAPIError as e:
                st.error(f'서버 응답 통신 중 오류가 발생했습니다. (상세 내역: {str(e)})')
                st.info('👉 해결방안: 문서 분량이 수백 페이지를 초과하는 경우 발생할 수 있습니다! 핵심 페이지(요약본) 위주로 파일을 압축하여 올려주시면 정상 작동합니다.')

    # --- 정성 분석 결과 인라인 표시 ---
    if st.session_state.get('analysis_done_B') and 'qual_report' in st.session_state:
        st.markdown("---")
        st.markdown("#### 📋 미래여건변화 분석 요약")
        qual_report = st.session_state['qual_report']
        import re
        sections = re.split(r'===SECTION_\d+===', qual_report)
        sec1 = sections[1].strip() if len(sections) > 1 else "데이터를 파싱할 수 없습니다."
        sec2 = sections[2].strip() if len(sections) > 2 else "데이터를 파싱할 수 없습니다."
        sec3 = sections[3].strip() if len(sections) > 3 else "데이터를 파싱할 수 없습니다."
        sec4 = sections[4].strip() if len(sections) > 4 else qual_report

        t_b1, t_b2, t_b3, t_b4 = st.tabs(["상위 및 관련계획", "인접 시·군 공간구조", "지역현안사항", "종합"])
        with t_b1:
            st.markdown(sec1)
        with t_b2:
            st.markdown(sec2)
        with t_b3:
            st.markdown(sec3)
        with t_b4:
            st.markdown(sec4)

    st.markdown("<br><hr>", unsafe_allow_html=True)

    # ==========================================
    # 🚀 Step C: 최종 종합 도출 UI
    # ==========================================
    cc1, cc2 = st.columns([5, 1])
    st.markdown("---")
    st.markdown("### 2-B. 대안설정 및 비교")
    st.markdown("#### (1) 공간구조 대안 비교")
    btn_alt = st.button("대안 비교 도출 (AI)", key="btn_alt", use_container_width=False)
    if btn_alt:
        with st.spinner("토지적성평가 등의 자료를 기반으로 대안을 비교 분석합니다..."):
            alt_prompt = f"[{st.session_state.get('result_sido', '')} {st.session_state.get('result_sigungu', '')}]의 공간구조 개편에 대한 2가지 대안(중심지체계, 개발축, 보전축)별 요약을 제시하고 장단점을 비교 분석하여 최종안 사유를 도출해 줘. 도시성장형태는 {st.session_state.get('growth_type', '')}을 기준으로 해."
            try:
                st.session_state['alt_report'] = get_gemini_response(alt_prompt, [], GEMINI_API_KEY)
            except Exception as e:
                pass
    if '_alt_report' in st.session_state or 'alt_report' in st.session_state:
        st.info(st.session_state.get('alt_report', ''))

    cc1, cc2 = st.columns([5, 1])
    cc1.markdown("#### (2) 공간구조 구상 (최종)")
    btn_c = cc2.button("분석 시작", key="btn_c", use_container_width=True, type="primary")
    
    if btn_c:
        if not (st.session_state.get('analysis_done_A') and st.session_state.get('analysis_done_B')):
            st.warning("⚠️ C단계를 진행하려면 먼저 상단의 A단계(정량)와 B단계(정성) 분석을 모두 완료해야 합니다!")
        else:
            with st.spinner("AI 수석 도시계획가가 종합 분석을 진행합니다... (약 1분 소요)"):
            
                sample_text = read_folder_documents("00. 샘플")
                top_zones = st.session_state['display_norm_df'].head(15).to_csv(index=False)
                qual_summary = st.session_state['qual_report']
            
                # 법정 지침 텍스트 구성 (캐시 확인 -> 폴더 확인 -> 없으면 기본 텍스트)
                DEFAULT_GUIDELINE_TEXT = """
    [도시·군기본계획수립지침 - 공간구조 설정 기준 (핵심 요약)]
    1. 공간구조는 해당 지자체의 장기적인 발전방향을 제시하고 인구 및 가구, 산업의 변화를 수용할 수 있도록 유연하게 설정해야 한다.
    2. 중심지 체계(도심, 부도심, 지역중심 등)는 대상 도시의 인구규모, 기능, 발전축 등을 종합적으로 고려하여 위계별로 명확히 구분 및 설정한다.
    3. 도심은 도시의 중추관리기능이 집중된 곳으로 육성하고, 부도심은 도심의 기능을 분담하여 광역적인 중심기능을 수행하도록 한다.
    4. 지역중심은 근린생활권의 중심지로서 지역주민의 일상생활에 필요한 서비스 기능을 집중적으로 제공할 수 있는 거점으로 설정한다.
    5. 공간구조 개편 시에는 기존의 중심지 체계를 객관적으로 진단하고, 쇠퇴 등 문제별 개선방안을 도출하여 새로운 발전축과 긴밀히 연계되도록 한다.
    6. 인구감소 및 저성장 추세에 적극 대응하여 무분별한 외곽 확장을 억제하고, 기존 도심 및 기성시가지의 재생 및 활성화를 최우선으로 고려하는 압축적 공간구조(Compact City)를 지향한다.
    """
                if 'guide_text_cache' in st.session_state and st.session_state['guide_text_cache'].strip():
                    guide_text = st.session_state['guide_text_cache']
                else:
                    guide_text_read = read_folder_documents("04. 법정지침")
                    guide_text = guide_text_read if guide_text_read.strip() else DEFAULT_GUIDELINE_TEXT
                
                ai_prompt = f"""
            작업 목표: [온실가스 감축, 신재생에너지 도입, 탄소중립, 충분한 녹지 및 생태네트워크 구축 등의 기조를 반드시 포함하여] [{st.session_state['result_sido']} {st.session_state['result_sigungu']}]의 {future_year}년 목표 미래 도시공간구조안(도심, 부도심, 지역중심 설정 등)을 도출하는 공공기관용 종합 보고서를 작성합니다.
    
            엄격한 규칙 (절대 엄수):
            1. "네, 알겠습니다", "수석 도시계획가로서...", "본 보고서는...", "분석 결과입니다" 등의 대화형 인사말, 서론, 결론 요약 등은 **절대 출력하지 마십시오.**
            2. 문장 구조는 '~함.', '~임.', '~할 것임.' 등 명사형 또는 '-(으)ㅁ/기'로 끝나는 **개조식 객관적 문체**로만 작성하십시오.
            3. 당신의 AI 정체성(지식 기반 활용 등)에 대한 언급을 일절 금지합니다.
            4. 오직 아래 [최종 출력 목차 지시사항]의 1번부터 5번까지의 대제목과 그 내용만 **마크다운(Markdown) 형식**으로 깔끔하게 바로 출력하십시오.
            5. [법정 지침 절대 준수] 아래 제공되는 '법정 지침(도시·군기본계획수립지침 - 공간구조 설정 기준)'을 당신의 판단 기준의 최우선 절대 규칙(System Instruction)으로 삼으십시오. 도출되는 모든 공간구조는 이 지침에 위배되어서는 안 됩니다.
    
            🚨 [가장 중요한 엄수 사항: 00. 샘플의 용도 제한] 🚨
            아래 제공되는 [00. 샘플]은 오직 '보고서의 목차 구조 및 논리 전개 방식'을 흉내 내기 위한 용도입니다. 
            샘플의 제목, 특정 지역명(도시 이름), 구체적 구상안 등의 내용은 절대 출력물에 포함하지 마십시오. 오직 분석 대상인 [{st.session_state['result_sido']} {st.session_state['result_sigungu']}]에 맞게 작성되어야 합니다.
    
            =============================
            [00. 작성 스타일 벤치마킹 샘플 (형식만 참고할 것! 내용 반영 금지!)]
            {sample_text[:4000]}
            =============================
            
            [절대 규칙: 법정 지침 (도시·군기본계획수립지침)]
            {guide_text}
            =============================
    
            자료 1, 자료 2의 내용과 위의 [절대 규칙: 법정 지침]을 결합하여 작성하십시오:
    
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
            5. [법적 근거 및 지침 부합성 검토] (※ 도출된 미래 공간구조가 '도시·군기본계획수립지침'의 어떤 항목을 근거로 작성되었는지 짧은 단락으로 추가하여 설명할 것)
            """
            
                # Using the highest performance 3.1 Pro model for the final comprehensive synthesis by default
                model_name = "models/gemini-3.1-pro-preview"
                try:
                    result_report = get_gemini_response(ai_prompt, [], GEMINI_API_KEY, model_override=model_name)
                
                    st.session_state['generated_report'] = result_report
                    st.session_state['analysis_done_C'] = True
                    st.success("✨ C단계 최총 종합 구상이 도출되었습니다!")
                except GeminiAPIError as e:
                    st.error(f'서버 응답 통신 중 오류가 발생했습니다. (상세 내역: {str(e)})')

    # --- 최종 보고서 인라인 표시 ---
    if st.session_state.get('analysis_done_C') and 'generated_report' in st.session_state:
        st.markdown("---")
        t_c1, t_c2 = st.tabs(["총괄보고서", "구상도"])
        with t_c1:
            st.markdown("### 🏛️ 최종 종합 도출 보고서")
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