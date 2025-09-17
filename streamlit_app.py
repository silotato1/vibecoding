import os
import time
from typing import Dict, Any, List, Optional, Union

import requests
import streamlit as st
from dotenv import load_dotenv


# -----------------------------
# 환경설정 & 유틸
# -----------------------------
load_dotenv()  # 로컬 개발 시 .env도 지원(배포 환경에서는 st.secrets 권장)

def _get_secret(name: str, default: Optional[Union[str, int]] = None):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default

# st.secrets 우선, 없으면 환경 변수로 폴백
YOUTUBE_API_KEY = _get_secret("YOUTUBE_API_KEY", os.getenv("YOUTUBE_API_KEY", ""))
DEFAULT_REGION = _get_secret("YOUTUBE_REGION", os.getenv("YOUTUBE_REGION", "KR"))
_max_results_raw = _get_secret("MAX_RESULTS", os.getenv("MAX_RESULTS", "30"))
try:
    DEFAULT_MAX_RESULTS = int(_max_results_raw) if _max_results_raw is not None else 30
except ValueError:
    DEFAULT_MAX_RESULTS = 30

# 로그인 정보(secrets 우선, 환경 변수 폴백)
AUTH_USERNAME = _get_secret("AUTH_USERNAME", os.getenv("AUTH_USERNAME", "admin"))
AUTH_PASSWORD = _get_secret("AUTH_PASSWORD", os.getenv("AUTH_PASSWORD", "changeme"))

YOUTUBE_VIDEOS_ENDPOINT = "https://www.googleapis.com/youtube/v3/videos"
YOUTUBE_CHANNELS_ENDPOINT = "https://www.googleapis.com/youtube/v3/channels"


def human_readable_views(n: str) -> str:
    """조회수(문자열 또는 숫자)를 보기 좋게 포맷팅(만/억/조 단위)."""
    return human_readable_number(n, "회")


def human_readable_number(n: str, unit: str) -> str:
    """한국식 큰수 표기(만/억/조)로 간략 표시 + 단위(예: 명, 개, 회).
    예) 1,730,000 -> 173만명, 27,700,000 -> 277만명
    """
    try:
        value = float(int(n))
    except Exception:
        # 이미 포맷된 문자열이면 그대로 반환
        return str(n)

    units = ["", "만", "억", "조", "경"]
    idx = 0
    while abs(value) >= 10000 and idx < len(units) - 1:
        value /= 10000.0
        idx += 1

    if idx == 0:
        return f"{int(value):,}{unit}"
    # 소수 첫째자리까지, .0은 제거
    compact = f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{compact}{units[idx]}{unit}"


@st.cache_data(ttl=300, show_spinner=False)
def fetch_popular_videos(api_key: str, region_code: str, max_results: int) -> Dict[str, Any]:
    """YouTube Data API로 인기 동영상 목록 가져오기."""
    params = {
        "part": "snippet,statistics",
        "chart": "mostPopular",
        "regionCode": region_code,
        "maxResults": max_results,
        "key": api_key,
    }
    resp = requests.get(YOUTUBE_VIDEOS_ENDPOINT, params=params, timeout=15)
    resp.raise_for_status()  # HTTP 오류 시 예외
    return resp.json()


@st.cache_data(ttl=300, show_spinner=False)
def fetch_channel_statistics(api_key: str, channel_ids: List[str]) -> Dict[str, Any]:
    """채널 구독자 수 등 통계를 한번에 조회(최대 50개).
    반환: {channelId: statistics(dict)}
    """
    if not channel_ids:
        return {}
    unique_ids = list(dict.fromkeys([cid for cid in channel_ids if cid]))  # 중복 제거, 순서 유지
    params = {
        "part": "statistics",
        "id": ",".join(unique_ids[:50]),  # videos API 최대 50과 동일 범위
        "key": api_key,
    }
    resp = requests.get(YOUTUBE_CHANNELS_ENDPOINT, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    out: Dict[str, Any] = {}
    for item in data.get("items", []):
        cid = item.get("id")
        out[cid] = item.get("statistics", {})
    return out


def validate_env() -> bool:
    if not YOUTUBE_API_KEY:
        st.error("YOUTUBE_API_KEY가 설정되지 않았습니다. 배포 시에는 .streamlit/secrets.toml에 설정하고, 로컬 개발 시에는 .env도 사용할 수 있습니다.")
        with st.expander("secrets.toml 예시(권장)"):
            st.code("""# .streamlit/secrets.toml
YOUTUBE_API_KEY = "YOUR_YOUTUBE_DATA_API_KEY"
YOUTUBE_REGION = "KR"
MAX_RESULTS = 30
AUTH_USERNAME = "admin"
AUTH_PASSWORD = "changeme"
""", language="toml")
        with st.expander(".env 예시(로컬 개발)"):
            st.code("""YOUTUBE_API_KEY=YOUR_YOUTUBE_DATA_API_KEY
YOUTUBE_REGION=KR
MAX_RESULTS=30
AUTH_USERNAME=admin
AUTH_PASSWORD=changeme
""", language="bash")
        st.stop()
    return True


def ensure_login() -> bool:
    """간단한 로그인 게이트. 성공 시 session_state에 플래그 저장."""
    if "is_authed" not in st.session_state:
        st.session_state.is_authed = False

    # 크리덴셜이 유효한지(빈값이 아닌지) 확인
    if not AUTH_USERNAME or not AUTH_PASSWORD:
        st.warning("로그인 자격 정보(AUTH_USERNAME/AUTH_PASSWORD)가 설정되지 않아 공개 모드로 동작합니다.")
        st.session_state.is_authed = True
        return True

    if st.session_state.is_authed:
        return True

    st.header("🔐 로그인")
    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("아이디", value="")
        password = st.text_input("비밀번호", type="password", value="")
        submitted = st.form_submit_button("로그인")

        if submitted:
            if username == str(AUTH_USERNAME) and password == str(AUTH_PASSWORD):
                st.session_state.is_authed = True
                st.success("로그인 성공")
                st.rerun()
            else:
                st.error("아이디 또는 비밀번호가 올바르지 않습니다.")
    return False


def render_video_item(item: Dict[str, Any], channel_stats_map: Dict[str, Any]):
    vid = item.get("id", "")
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})

    title = snippet.get("title", "(제목 없음)")
    channel = snippet.get("channelTitle", "(채널 정보 없음)")
    channel_id = snippet.get("channelId", "")
    thumbs = snippet.get("thumbnails", {})
    thumb_url = (
        thumbs.get("medium", {}).get("url")
        or thumbs.get("high", {}).get("url")
        or thumbs.get("default", {}).get("url")
    )
    views = human_readable_number(stats.get("viewCount", "0"), "회")
    likes = human_readable_number(stats.get("likeCount", "0"), "개") if stats.get("likeCount") is not None else "비공개"
    comments = human_readable_number(stats.get("commentCount", "0"), "개") if stats.get("commentCount") is not None else "비공개"
    video_url = f"https://www.youtube.com/watch?v={vid}"

    # 채널 구독자 수 조회
    subs_text = "비공개"
    if channel_id and channel_id in channel_stats_map:
        ch_stats = channel_stats_map[channel_id] or {}
        subs = ch_stats.get("subscriberCount")
        if subs is not None:
            subs_text = human_readable_number(subs, "명")

    left, right = st.columns([1, 3], vertical_alignment="center")
    with left:
        if thumb_url:
            st.image(thumb_url, use_container_width=True)
        else:
            st.write("(썸네일 없음)")
    with right:
        st.markdown(f"**[{title}]({video_url})**")
        st.caption(f"채널: {channel} · 구독자: {subs_text}")
        st.caption(f"조회수: {views} · 좋아요: {likes} · 댓글: {comments}")


def main():
    st.set_page_config(page_title="YouTube 인기 동영상", page_icon="📺", layout="wide")
    st.title("📺 YouTube 인기 동영상")
    st.caption("간단한 YouTube Data API 예제 · 지역/개수 조절 가능 · 5분 캐시")

    validate_env()

    # 로그인 게이트
    if not ensure_login():
        return

    with st.sidebar:
        st.subheader("옵션")
        # 로그아웃 버튼
        if st.button("로그아웃", type="secondary"):
            st.session_state.is_authed = False
            fetch_popular_videos.clear()
            fetch_channel_statistics.clear()
            st.rerun()
        region_presets = [
            ("KR", "대한민국"),
            ("US", "미국"),
            ("JP", "일본"),
            ("GB", "영국"),
            ("DE", "독일"),
            ("FR", "프랑스"),
            ("IN", "인도"),
            ("ID", "인도네시아"),
            ("VN", "베트남"),
            ("BR", "브라질"),
            ("CA", "캐나다"),
            ("AU", "호주"),
        ]
        display_options = [f"{name} ({code})" for code, name in region_presets] + ["직접 입력(Custom)..."]
        code_list = [code for code, _ in region_presets]
        try:
            default_index = code_list.index(DEFAULT_REGION)
        except ValueError:
            default_index = 0
        region_choice = st.selectbox("지역 선택", options=display_options, index=default_index)
        if region_choice == "직접 입력(Custom)...":
            region = st.text_input("지역 코드 직접 입력 (ISO 3166-1 Alpha-2)", value=DEFAULT_REGION)
        else:
            # "대한민국 (KR)" 형태에서 코드 추출
            region = region_choice.split("(")[-1].strip(")")

        max_results = st.slider("표시 개수", min_value=5, max_value=50, value=min(DEFAULT_MAX_RESULTS, 30), step=5)
        st.divider()
        refresh = st.button("🔄 새로고침")
        if refresh:
            fetch_popular_videos.clear()
            fetch_channel_statistics.clear()
            st.experimental_rerun()

    try:
        with st.spinner("인기 동영상을 불러오는 중..."):
            data = fetch_popular_videos(YOUTUBE_API_KEY, region, max_results)
    except requests.HTTPError as e:
        status = getattr(e.response, "status_code", "-")
        try:
            err_json = e.response.json()
        except Exception:
            err_json = {"error": str(e)}
        st.error(f"API 요청 실패: HTTP {status}")
        with st.expander("오류 상세"):
            st.json(err_json)
        return
    except requests.Timeout:
        st.error("요청 시간이 초과되었습니다. 네트워크 상태를 확인하거나 잠시 후 다시 시도하세요.")
        return
    except Exception as e:
        st.error(f"예상치 못한 오류가 발생했습니다: {e}")
        return

    items: List[Dict[str, Any]] = data.get("items", [])
    if not items:
        st.warning("표시할 동영상이 없습니다. 지역 코드를 변경하거나 잠시 후 새로고침해 보세요.")
        return

    st.write(f"총 {len(items)}개 결과")
    st.divider()

    # 채널 통계 가져오기(구독자 수)
    channel_ids = [it.get("snippet", {}).get("channelId", "") for it in items]
    try:
        channel_stats_map = fetch_channel_statistics(YOUTUBE_API_KEY, channel_ids)
    except Exception:
        channel_stats_map = {}

    for item in items:
        render_video_item(item, channel_stats_map)
        st.markdown("---")

    st.caption(f"마지막 업데이트: {time.strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
