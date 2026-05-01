"""
Threads 최신 포스트에 CTA 댓글 자동 등록 (GitHub Actions 전용).
환경변수: THREADS_ACCESS_TOKEN, THREADS_USER_ID, ANTHROPIC_API_KEY
"""
import os
import sys
import time
from datetime import datetime, timezone, timedelta

import requests

THREADS_TOKEN   = os.environ["THREADS_ACCESS_TOKEN"]
THREADS_USER_ID = os.environ["THREADS_USER_ID"]
ANTHROPIC_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")
BASE            = "https://graph.threads.net/v1.0"
LOOK_BACK_MIN   = 90  # 최근 90분 이내 포스트 탐색

# ── CTA 생성 ──────────────────────────────────────────────────

_SYSTEM = """너는 AdSmartPlanner 공식 Threads 계정이야.
방금 올린 포스트에 첫 번째 댓글로 달 CTA를 써줘.

규칙:
- 포스트 본문 맥락을 1문장으로 자연스럽게 이어받은 뒤 행동 유도
- 말투는 반말(해체) — 포스트 톤과 일치
- 마지막 줄은 반드시: www.adsmartplanner.com
- 전체 5줄 이내, 이모지 없음
- "7일 무료" 또는 "무료 체험" 포함
- 브랜드명: AdSmartPlanner"""

_FALLBACK = (
    "한 번 직접 계산해봐.\n\n"
    "7일 무료 체험으로 내 상품 손익분기점부터 확인해봐.\n"
    "www.adsmartplanner.com"
)


def generate_cta(post_text: str) -> str:
    if not ANTHROPIC_KEY:
        return _FALLBACK
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system=_SYSTEM,
            messages=[{"role": "user", "content": f"포스트 본문:\n{post_text[:400]}"}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        print(f"[warn] Claude 실패: {e}")
        return _FALLBACK


# ── Threads API ────────────────────────────────────────────────

def get_recent_top_posts() -> list:
    since_ts = int((datetime.now(timezone.utc) - timedelta(minutes=LOOK_BACK_MIN)).timestamp())
    res = requests.get(
        f"{BASE}/{THREADS_USER_ID}/threads",
        params={
            "access_token": THREADS_TOKEN,
            "fields": "id,text,timestamp,reply_to_id",
            "since": since_ts,
            "limit": 10,
        },
        timeout=15,
    )
    res.raise_for_status()
    all_posts = res.json().get("data", [])
    return [p for p in all_posts if not p.get("reply_to_id")]


def has_my_reply(post_id: str) -> bool:
    res = requests.get(
        f"{BASE}/{post_id}/replies",
        params={"access_token": THREADS_TOKEN, "fields": "id"},
        timeout=10,
    )
    if not res.ok:
        return False
    return len(res.json().get("data", [])) > 0


def post_reply(parent_id: str, text: str) -> str | None:
    res = requests.post(
        f"{BASE}/{THREADS_USER_ID}/threads",
        params={"access_token": THREADS_TOKEN},
        json={"media_type": "TEXT", "text": text, "reply_to_id": parent_id},
        timeout=15,
    )
    if not res.ok:
        print(f"[error] 댓글 컨테이너 실패: {res.text[:200]}")
        return None
    container_id = res.json()["id"]
    time.sleep(5)
    pub = requests.post(
        f"{BASE}/{THREADS_USER_ID}/threads_publish",
        params={"access_token": THREADS_TOKEN},
        json={"creation_id": container_id},
        timeout=15,
    )
    if not pub.ok:
        print(f"[error] 댓글 발행 실패: {pub.text[:200]}")
        return None
    return pub.json().get("id")


# ── 메인 ───────────────────────────────────────────────────────

def main():
    print(f"[{datetime.now(timezone.utc).isoformat()}] 실행 시작")
    posts = get_recent_top_posts()
    if not posts:
        print("최근 발행된 포스트 없음 — 종료")
        return

    print(f"포스트 {len(posts)}개 발견")
    success = 0
    for post in posts:
        pid   = post["id"]
        text  = post.get("text", "")
        ts    = post.get("timestamp", "")
        print(f"\n  [{pid}] {ts}")
        print(f"  내용: {text[:60]}")

        if has_my_reply(pid):
            print("  이미 댓글 있음 — 스킵")
            continue

        cta = generate_cta(text)
        print(f"  생성된 CTA:\n{cta}")

        reply_id = post_reply(pid, cta)
        if reply_id:
            print(f"  댓글 등록 완료: {reply_id}")
            success += 1
        else:
            print("  댓글 등록 실패")
            sys.exit(1)

    print(f"\n완료: {success}개 댓글 등록")


if __name__ == "__main__":
    main()
