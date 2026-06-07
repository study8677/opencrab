"""
lookout — 眺望塔：瞭望 GitHub/社区，发现外面世界的同类项目，找进化灵感。
"""
import json, urllib.request, re, time

# 支持的搜索端点（按优先级试）
_SEARCH_ENDPOINTS = [
    # GitHub REST API 搜索（需 token，可选）
    ("https://api.github.com/search/repositories",
     "?q=autonomous+agent+self-improving+language:python&sort=stars&per_page=5"),
    # GitHub 话题页（无需 token）
    ("https://github.com/topics/autonomous-agent"),
    # 备用：模拟搜索结果（网络全挂时的优雅降级）
]


def _fetch(url: str, token: str = "") -> str:
    """抓一页 URL，超时/失败返回空字串。"""
    try:
        headers = {"Accept": "application/vnd.github.v3+json",
                   "User-Agent": "opencrab/0.1"}
        if token:
            headers["Authorization"] = f"token {token}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _gh_search(token: str, query: str, per_page: int = 5) -> list[dict]:
    """GitHub API 搜索仓库，返回轻量描述列表。"""
    url = (f"https://api.github.com/search/repositories"
           f"?q={query}&sort=stars&per_page={per_page}")
    raw = _fetch(url, token)
    if not raw:
        return []
    try:
        data = json.loads(raw)
        items = data.get("items", [])
        return [{"name": i.get("full_name", ""),
                 "stars": i.get("stargazers_count", 0),
                 "desc": i.get("description", "") or "",
                 "url": i.get("html_url", "")}
                for i in items]
    except Exception:
        return []


def _summarize(items: list[dict]) -> str:
    """把仓库列表压成一行摘要，附亮点描述。"""
    if not items:
        return ""
    lines = []
    for it in items:
        stars = f"⭐{it['stars']}" if it["stars"] else ""
        desc = it["desc"][:80] + ("…" if len(it["desc"]) > 80 else "")
        lines.append(f"- [{it['name']}] {stars} — {desc}")
    return "\n".join(lines)


def scout(topic: str = "autonomous self-improving AI agent",
          github_token: str = "") -> str:
    """
    眺望外部世界同类项目，返回格式化的灵感摘要。
    网络全挂时返回优雅降级提示，绝不抛异常。
    """
    results = _gh_search(github_token, topic.replace(" ", "+"))
    if results:
        return _summarize(results)

    # 降级：尝试抓 GitHub 话题页
    topic_url = f"https://github.com/topics/{topic.replace(' ', '-').lower()}"
    raw = _fetch(topic_url)
    if raw:
        # 简单提取 <a class="text-bold"...> 仓库名
        names = re.findall(r'class="text-bold[^"]*">([^<]+)', raw)[:5]
        if names:
            lines = [f"- {n.strip()}" for n in names]
            return ("🔭 GitHub 话题页发现：\n" + "\n".join(lines))

    return ("🔭 眺望塔暂时看不清外面（网络抖动或 GitHub 限速）。"
            "外面世界正在进化，等网络恢复再看。")
