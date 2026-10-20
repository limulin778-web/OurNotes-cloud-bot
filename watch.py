#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OurNotes cloud update watcher.

Runs on GitHub Actions (or any always-on server). It polls:
  - QooApp international page for the client version
  - StarMoe-org/moenotes-masterdata current_version.json for master version

When a version changes it sends a push via PUSH_URL and updates state.json.
The workflow then commits state.json back to the repository.
"""

import os
import re
import json
import base64
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(ROOT, "state.json")

QOO_URLS = [
    "https://apps.qqaoop.com/app/156979",
    "https://apps.qqaoop.com/en/app/156979",
]
REPO = "StarMoe-org/moenotes-masterdata"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

PUSH_TYPE = os.getenv("PUSH_TYPE", "json").strip().lower()
PUSH_URL = os.getenv("PUSH_URL", "").strip()
PUSH_TOKEN = os.getenv("PUSH_TOKEN", "").strip()
PUSH_CHAT_ID = os.getenv("PUSH_CHAT_ID", "").strip()


def log(msg):
    print(msg, flush=True)


def fetch(url, timeout=30):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return raw.decode("utf-8", "replace")


def get_qooapp():
    last_err = None
    for url in QOO_URLS:
        try:
            html = fetch(url)
        except Exception as e:
            last_err = e
            continue
        m = re.search(r'"softwareVersion"\s*:\s*"([^"]+)"', html)
        if m:
            return {"version": m.group(1).strip(), "url": url}
        # fallback: some builds expose a version in a meta tag / json block
        m = re.search(r'"versionName"\s*:\s*"([^"]+)"', html)
        if m:
            return {"version": m.group(1).strip(), "url": url}
        last_err = RuntimeError("softwareVersion not found")
    if last_err:
        log("QooApp 读取失败: %s" % last_err)
    return None


def get_masterdata():
    url = "https://api.github.com/repos/%s/contents/current_version.json?ref=main" % REPO
    try:
        raw = fetch(url)
        obj = json.loads(raw)
        content = base64.b64decode(obj["content"]).decode("utf-8")
        data = json.loads(content)
        cur = data["regions"]["hk-tw-mo"]
        return {
            "client": cur.get("client_version"),
            "master": cur.get("version"),
            "resource": cur.get("resource_version"),
            "url": "https://github.com/%s/blob/main/current_version.json" % REPO,
        }
    except Exception as e:
        log("masterdata 读取失败: %s" % e)
        return None


def get_official_news():
    url = (
        "https://l11-web-api.biligames.com/game/news/page"
        "?page_num=1&page_size=5&game_base_id=118241&show_position=1&lang=zh"
    )
    try:
        obj = json.loads(fetch(url))
        items = obj["data"]["list"]
        out = []
        for it in items:
            out.append({
                "id": str(it.get("news_id", "")),
                "title": it.get("title", ""),
                "time": it.get("publish_time", ""),
                "url": "https://bdon.biligames.com/details/?id=%s" % it.get("news_id", ""),
            })
        return out
    except Exception as e:
        log("官方新闻读取失败: %s" % e)
        return None


def load_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, STATE_PATH)


def push(title, content):
    if not PUSH_URL:
        log("未配置 PUSH_URL；本次只打印，不发送推送。")
        log(title)
        log(content)
        return False
    try:
        if PUSH_TYPE == "bark":
            body = json.dumps({"title": title, "body": content}, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(PUSH_URL, data=body, headers={"Content-Type": "application/json; charset=utf-8"})
            urllib.request.urlopen(req, timeout=20).read()
        elif PUSH_TYPE == "serverchan":
            body = urllib.parse.urlencode({"title": title, "desp": content}).encode("utf-8")
            req = urllib.request.Request(PUSH_URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
            urllib.request.urlopen(req, timeout=20).read()
        elif PUSH_TYPE == "pushplus":
            body = json.dumps({
                "token": PUSH_TOKEN,
                "title": title,
                "content": content,
                "template": "txt",
            }, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(PUSH_URL, data=body, headers={"Content-Type": "application/json; charset=utf-8"})
            urllib.request.urlopen(req, timeout=20).read()
        elif PUSH_TYPE == "telegram":
            body = json.dumps({"chat_id": PUSH_CHAT_ID, "text": title + "\n" + content}, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(PUSH_URL, data=body, headers={"Content-Type": "application/json; charset=utf-8"})
            urllib.request.urlopen(req, timeout=20).read()
        elif PUSH_TYPE == "discord":
            body = json.dumps({"content": title + "\n" + content}, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(PUSH_URL, data=body, headers={"Content-Type": "application/json; charset=utf-8"})
            urllib.request.urlopen(req, timeout=20).read()
        elif PUSH_TYPE == "wecom":
            body = json.dumps({
                "msgtype": "text",
                "text": {"content": title + "\n" + content},
            }, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(PUSH_URL, data=body, headers={"Content-Type": "application/json; charset=utf-8"})
            urllib.request.urlopen(req, timeout=20).read()
        else:  # generic json
            body = json.dumps({
                "title": title,
                "text": content,
                "content": content,
            }, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(PUSH_URL, data=body, headers={"Content-Type": "application/json; charset=utf-8"})
            urllib.request.urlopen(req, timeout=20).read()
        log("推送已发送。")
        return True
    except Exception as e:
        log("推送失败: %s" % e)
        return False


def main():
    now = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    log("=== OurNotes cloud watcher %s ===" % now)

    if os.getenv("FORCE_TEST", "").strip().lower() in ("1", "true", "yes"):
        push("【OurNotes 测试】", "这是一条测试推送；收到说明 Webhook 配置正常。")
        return

    qoo = get_qooapp()
    master = get_masterdata()
    news = get_official_news()
    if qoo:
        log("QooApp: %s -> %s" % (qoo["url"], qoo["version"]))
    if master:
        log("masterdata: client=%s master=%s resource=%s" % (master["client"], master["master"], master["resource"]))
    if news:
        log("官方新闻最新一条: %s %s" % (news[0]["time"], news[0]["title"]))

    state = load_state()

    # 首次运行只建立基线
    if not state:
        new_state = {
            "qooapp_version": qoo["version"] if qoo else "",
            "repo_client": master["client"] if master else "",
            "master_version": master["master"] if master else "",
            "resource_version": master["resource"] if master else "",
            "last_news_id": news[0]["id"] if news else "",
            "updated_at": now,
        }
        save_state(new_state)
        log("首次运行，已记录基线，不推送。")
        return

    alerts = []
    changed = False

    if qoo and state.get("qooapp_version") and qoo["version"] != state.get("qooapp_version"):
        alerts.append(
            "应用商店/客户端版本变化：%s -> %s\n%s"
            % (state.get("qooapp_version"), qoo["version"], qoo["url"])
        )
        changed = True

    if master:
        if state.get("master_version") and master["master"] != state.get("master_version"):
            alerts.append(
                "Master 版本变化：%s -> %s\n%s"
                % (state.get("master_version"), master["master"], master["url"])
            )
            changed = True
        if state.get("repo_client") and master["client"] != state.get("repo_client"):
            alerts.append(
                "masterdata 显示客户端版本变化：%s -> %s"
                % (state.get("repo_client"), master["client"])
            )
            changed = True
        if state.get("resource_version") and master["resource"] != state.get("resource_version"):
            alerts.append(
                "资源版本变化（可能是热更新/新资源预载）：%s -> %s"
                % (state.get("resource_version"), master["resource"])
            )
            changed = True

    news_changed = False
    if news:
        latest_news_id = news[0]["id"]
        old_news_id = state.get("last_news_id", "")
        if old_news_id and latest_news_id != old_news_id:
            new_items = []
            for it in news:
                if it["id"] == old_news_id:
                    break
                new_items.append(it)
            keywords = re.compile(r"更新|維護|维护|版本|活動|活动|新活動|新活动|卡池|劇情|剧情|故事|改版|開服|开服")
            interesting = [it for it in new_items if keywords.search(it["title"])]
            if interesting:
                lines = []
                for it in interesting[:3]:
                    lines.append("%s %s\n%s" % (it["time"], it["title"], it["url"]))
                alerts.append("官方新闻更新：\n" + "\n".join(lines))
                changed = True
            else:
                log("官方新闻有变化，但未命中更新/活动关键词：%s" % (new_items[0]["title"] if new_items else ""))
            state["last_news_id"] = latest_news_id
            news_changed = True
        elif not old_news_id:
            state["last_news_id"] = latest_news_id
            news_changed = True

    if not changed:
        if news_changed:
            state["updated_at"] = now
            save_state(state)
            log("state.json 已更新（新闻基线）。")
        else:
            log("无版本变化。")
        return

    title = "【OurNotes 更新】"
    content = "检测到 OurNotes 更新：\n\n" + "\n\n".join(alerts)
    content += "\n\n更新后流程：应用商店更新 -> 启动游戏到主页 -> 运行 Start-Patch.cmd -> 重启游戏。"
    content += "\n如果只是 Master 更新、客户端版本没变，静态补丁通常仍然有效；建议重跑 Start-Patch.cmd 确认。"

    sent = push(title, content)
    if not sent:
        log("推送未成功，state 不更新，下一轮会重试。")
        return

    state["qooapp_version"] = qoo["version"] if qoo else state.get("qooapp_version", "")
    if master:
        state["repo_client"] = master["client"]
        state["master_version"] = master["master"]
        state["resource_version"] = master["resource"]
    state["updated_at"] = now
    save_state(state)
    log("state.json 已更新。")


if __name__ == "__main__":
    main()
