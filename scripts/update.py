#!/usr/bin/env python3
"""Copy every post, comment and image from the Blogger blog into this repo.

Reads the blog address from config.json, downloads the public feeds, saves
each image once into images/, and writes data/posts.json for the website.
Safe to run again and again: images already saved are not downloaded twice,
and a post that disappears from the blog stays in the archive.
Only the Python standard library is used.
"""
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))
BLOG = CONFIG["blog"].rstrip("/")
DATA = os.path.join(ROOT, "data", "posts.json")
IMG_DIR = os.path.join(ROOT, "images")
UA = {"User-Agent": "Mozilla/5.0 (archive bot for our own blog)"}

IMG_RE = re.compile(
    # A ")" is part of the URL only as a balanced pair, e.g. "photo (1).jpg";
    # a lone ")" (end of a CSS url(...)) still ends the match.
    r"https?://(?:blogger\.googleusercontent\.com/img/|\d\.bp\.blogspot\.com/)"
    r"(?:[^\"' ()<>]|\([^\"' ()<>]*\))+",
    re.I,
)
# <img src="https://other-site/..."> : images the posts link from other websites
EXT_IMG_RE = re.compile(r"(<img\b[^>]*?\ssrc=[\"'])(https?://[^\"']+)([\"'])", re.I)
FAILED_FILE = os.path.join(ROOT, "data", "failed-images.json")
RETRY_AFTER = 30 * 24 * 3600
FAILED = {}  # external image URL -> time of the last failed attempt
EXT = {"image/png": "png", "image/gif": "gif", "image/webp": "webp",
       "image/bmp": "bmp", "image/jpeg": "jpg", "image/svg+xml": "svg"}


def get(url, tries=5, timeout=60, max_bytes=None):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read(max_bytes + 1) if max_bytes else r.read()
                if max_bytes and len(body) > max_bytes:
                    raise ValueError("file too big")
                return body, r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            if e.code in (403, 404, 410):
                raise
            wait = 5 * (i + 1) ** 2
        except ValueError:
            raise
        except Exception:
            wait = 5 * (i + 1) ** 2
        if i < tries - 1:
            time.sleep(wait)
    raise RuntimeError("gave up on " + url)


def feed(path):
    out, start = [], 1
    while True:
        body, _ = get(f"{BLOG}{path}?alt=json&max-results=150&start-index={start}")
        entries = json.loads(body)["feed"].get("entry", [])
        out += entries
        if len(entries) < 150:
            return out
        start += 150


def link(e):
    return next((l["href"] for l in e.get("link", []) if l.get("rel") == "alternate"), "")


def save_image(url, known, external=False):
    """Return the local path for an image URL, downloading it if needed.

    external=True is for images hosted on other websites: they fail fast
    (many are long dead), and a failure is remembered for 30 days so the
    nightly run doesn't keep retrying them.
    """
    clean = url.replace("&amp;", "&")
    key = hashlib.sha1(clean.encode()).hexdigest()[:16]
    if key in known:
        return known[key]
    for f in os.listdir(IMG_DIR):
        if f.startswith(key + "."):
            known[key] = "images/" + f
            return known[key]
    if external and time.time() - FAILED.get(clean, 0) < RETRY_AFTER:
        return None
    try:
        if external:
            body, ctype = get(clean, tries=2, timeout=20, max_bytes=25_000_000)
            if not ctype.lower().startswith("image/") or not body:
                raise ValueError("not an image: " + ctype)
        else:
            body, ctype = get(clean)
    except Exception as e:
        print("  image failed:", clean[:90], e)
        if external:
            FAILED[clean] = int(time.time())
        return None
    FAILED.pop(clean, None)
    name = f"{key}.{EXT.get(ctype.split(';')[0].strip(), 'jpg')}"
    with open(os.path.join(IMG_DIR, name), "wb") as fh:
        fh.write(body)
    known[key] = "images/" + name
    time.sleep(0.5)
    return known[key]


def main():
    if "CHANGE-ME" in BLOG:
        sys.exit("Put the blog address into config.json first.")
    os.makedirs(IMG_DIR, exist_ok=True)
    old = {}
    if os.path.exists(DATA):
        for p in json.load(open(DATA, encoding="utf-8"))["posts"]:
            old[p["id"]] = p

    posts = feed("/feeds/posts/default")
    try:
        comments = feed("/feeds/comments/default")
    except Exception as e:
        print("comments feed not available:", e)
        comments = []
    print(f"{len(posts)} posts, {len(comments)} comments on the blog")

    by_post = {}
    for c in comments:
        ref = (c.get("thr$in-reply-to") or {}).get("ref")
        if ref:
            by_post.setdefault(ref, []).append({
                "author": c["author"][0]["name"]["$t"],
                "published": c["published"]["$t"],
                "html": (c.get("content") or c.get("summary") or {}).get("$t", ""),
            })

    if os.path.exists(FAILED_FILE):
        FAILED.update(json.load(open(FAILED_FILE, encoding="utf-8")))
    known, missing, ext_missing = {}, 0, 0
    current = {}
    for e in posts:
        pid = e["id"]["$t"]
        html = (e.get("content") or {}).get("$t", "")

        def repl(m):
            nonlocal missing
            local = save_image(m.group(0), known)
            if local is None:
                missing += 1
                return m.group(0)
            return local

        def repl_ext(m):
            nonlocal ext_missing
            local = save_image(m.group(2), known, external=True)
            if local is None:
                ext_missing += 1
                return m.group(0)
            return m.group(1) + local + m.group(3)

        html = EXT_IMG_RE.sub(repl_ext, IMG_RE.sub(repl, html))

        current[pid] = {
            "id": pid,
            "title": e["title"]["$t"],
            "published": e["published"]["$t"],
            "updated": e["updated"]["$t"],
            "author": e["author"][0]["name"]["$t"],
            "labels": sorted(c["term"] for c in e.get("category", [])),
            "url": link(e),
            "html": html,
            "comments": sorted(by_post.get(pid, []), key=lambda c: c["published"]),
        }

    # Keep posts that were deleted from the blog: this repo is the backup.
    # Only posts from this same blog: after switching to another blog address
    # the old copies are dropped, so imported posts don't show up twice.
    blog_id = posts[0]["id"]["$t"].split(".post-")[0] if posts else None
    for pid, p in old.items():
        if pid not in current and blog_id and pid.startswith(blog_id + ".post-"):
            p["removedFromBlog"] = True
            current[pid] = p

    all_posts = sorted(current.values(), key=lambda p: p["published"], reverse=True)
    os.makedirs(os.path.dirname(DATA), exist_ok=True)
    with open(DATA, "w", encoding="utf-8") as fh:
        json.dump({"blog": BLOG, "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "posts": all_posts}, fh, ensure_ascii=False, indent=0)
    # A small file that changes every night, so GitHub sees the repository as
    # active and never pauses the nightly job (it does that after 60 quiet days).
    with open(os.path.join(ROOT, "data", "last-run.txt"), "w") as fh:
        fh.write(time.strftime("%Y-%m-%d %H:%M UTC\n", time.gmtime()))
    with open(FAILED_FILE, "w", encoding="utf-8") as fh:
        json.dump(FAILED, fh, indent=0)
    print(f"saved {len(all_posts)} posts, {len(known)} images, {missing} Blogger images "
          f"unreachable, {ext_missing} images on other websites unreachable")


if __name__ == "__main__":
    main()
