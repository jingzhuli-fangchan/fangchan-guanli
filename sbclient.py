"""Supabase 最小客户端（只用 Python 标准库，不用装任何包）。

用途：给 upload-seed.py / sync-excel-to-supabase.py 用。
认证：用邮箱+密码登录拿 access_token（RLS 要求 authenticated 身份），
      走 GoTrue /auth/v1/token?grant_type=password。
数据：走 PostgREST /rest/v1/leads，带 Bearer token。

凭证一律走环境变量，绝不写进文件：
  SUPABASE_URL        默认 https://sjdnqqacbjbqclduohsi.supabase.co
  SUPABASE_ANON_KEY   默认用工作台 index.html 里那个 anon key（公开 key，只用于调接口）
  LEADS_SYNC_EMAIL    登录邮箱（必填）
  LEADS_SYNC_PASSWORD 登录密码（必填）
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_URL = "https://sjdnqqacbjbqclduohsi.supabase.co"
DEFAULT_ANON = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNqZG"
                "5xcWFjYmpicWNsZHVvaHNpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTIyNTEzOTMsImV4cCI6"
                "MjEwNzgyNzM5M30.2ISX0I-pfhWcIQlf1L0GrlWKtoAxsKjRCemZ1QJipVA")


class SupabaseError(Exception):
    pass


class Client:
    def __init__(self, url=None, anon=None):
        self.url = (url or os.environ.get("SUPABASE_URL") or DEFAULT_URL).rstrip("/")
        self.anon = anon or os.environ.get("SUPABASE_ANON_KEY") or DEFAULT_ANON
        self.token = None

    def login(self, email=None, password=None):
        email = email or os.environ.get("LEADS_SYNC_EMAIL")
        password = password or os.environ.get("LEADS_SYNC_PASSWORD")
        if not email or not password:
            raise SupabaseError("缺少登录凭证：请设置环境变量 LEADS_SYNC_EMAIL 和 LEADS_SYNC_PASSWORD")
        body = json.dumps({"email": email, "password": password}).encode()
        req = urllib.request.Request(
            self.url + "/auth/v1/token?grant_type=password",
            data=body, method="POST",
            headers={"Content-Type": "application/json", "apikey": self.anon},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            raise SupabaseError(f"登录失败 HTTP {e.code}: {detail[:300]}")
        except Exception as e:
            raise SupabaseError(f"登录失败（网络/项目未恢复？）: {e}")
        self.token = data.get("access_token")
        if not self.token:
            raise SupabaseError(f"登录未返回 token: {str(data)[:200]}")
        return data.get("user", {}).get("email", email)

    def _req(self, method, path, params=None, body=None, extra_headers=None):
        url = self.url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {
            "apikey": self.anon,
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        if extra_headers:
            headers.update(extra_headers)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read().decode()
                return json.loads(raw) if raw else []
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            raise SupabaseError(f"{method} {path} HTTP {e.code}: {detail[:500]}")

    def select_leads(self, columns="id,space_id,seq,name,douyin_id,phone,phone_clean,wechat,"
                     "customer_name,wechat_name,remark,follow_status,sheet_status,intent,"
                     "region,source,first_seen_date,lead_time,next_follow_up,pinned,follow_logs"):
        """拉全部线索（分页拉，每页 1000 条）。"""
        out, offset = [], 0
        while True:
            rows = self._req("GET", "/rest/v1/leads",
                             params={"select": columns, "order": "lead_time.desc",
                                     "limit": 1000, "offset": offset})
            if not rows:
                break
            out.extend(rows)
            if len(rows) < 1000:
                break
            offset += 1000
        return out

    def insert_lead(self, row):
        return self._req("POST", "/rest/v1/leads", body=[row])

    def update_lead(self, lead_id, patch):
        return self._req("PATCH", "/rest/v1/leads",
                         params={"id": f"eq.{lead_id}"}, body=patch)
