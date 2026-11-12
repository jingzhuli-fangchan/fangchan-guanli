#!/usr/bin/env python3
"""抖音来客线索表.xlsx -> Supabase leads 表 增量同步。

规则（与 Muse 空间每晚 21:05 的 Excel->空间同步同款）：
  1. 只追加新于库内最新留资时间的线索；按人去重：同一抖音号或同一完整电话算同一人。
  2. 已存在的人：仅当 Excel 里的留资时间更新时，才更新“表格字段”
     （抖音名/抖音号/电话/微信/归属地/来源/意向/表格状态/留资时间）。
  3. 绝不覆盖：跟进状态、跟进记录、备注（客户姓名/微信名/其他说明）、
     置顶、下次跟进日期。
  4. 抖音号和完整电话都没有的行跳过（无法去重，防重复插入）。
  5. 打码电话（带 *）和“未留电话”不参与电话匹配。

用法：
  LEADS_SYNC_EMAIL=xxx@xxx LEADS_SYNC_PASSWORD='...' \
      python3 sync-excel-to-supabase.py [--excel PATH] [--dry-run]

  --excel   默认 ~/workspace/goals/goal-7/files/抖音来客线索表.xlsx
  --dry-run 只打印要做什么，不写库（建议每次先 dry-run 看一眼）
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sbclient import Client, SupabaseError

DEFAULT_EXCEL = os.path.expanduser(
    "~/workspace/goals/goal-7/files/抖音来客线索表.xlsx")

# 同步时可更新的“表格字段”（其余字段一律不动）
SHEET_FIELDS = ["name", "douyin_id", "phone", "phone_clean", "wechat",
                "region", "source", "intent", "sheet_status", "lead_time"]


def _retry(fn, label, tries=6, sleep=8):
    """链路抖动严重：失败就等几秒重跑，耗尽才抛错。
    HTTP 4xx 是请求本身的问题，重试也没用，直接抛。"""
    last = None
    for i in range(1, tries + 1):
        try:
            return fn()
        except Exception as e:
            last = e
            if isinstance(e, SupabaseError) and "HTTP 4" in str(e):
                raise
            print(f"  [{label}] 第 {i}/{tries} 次失败：{str(e)[:120]}")
            if i < tries:
                time.sleep(sleep)
    raise last


def fetch_existing(client):
    """分页拉库内线索：每页 20 条、只取比对用的 4 个字段，
    单个响应很小，不容易被抖动的链路截断。"""
    out, offset = [], 0
    cols = "id,douyin_id,phone_clean,lead_time"
    while True:
        page = _retry(
            lambda o=offset: client._req(
                "GET", "/rest/v1/leads",
                params={"select": cols, "order": "lead_time.desc",
                        "limit": 20, "offset": o}),
            f"读库 offset={offset}")
        if not page:
            break
        out.extend(page)
        if len(page) < 20:
            break
        offset += 20
    return out


def clean_phone(v):
    """完整 11 位手机号才返回数字串；打码/未留/空返回 None。"""
    if v is None:
        return None
    digits = re.sub(r"\D", "", str(v))
    return digits if re.fullmatch(r"1\d{10}", digits) else None


def parse_time(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    s = str(v).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def read_excel(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header = [str(c).strip() if c is not None else "" for c in rows[0]]
    idx = {name: i for i, name in enumerate(header)}
    out = []
    for r in rows[1:]:
        if not r or r[idx["姓名/昵称"]] is None:
            continue
        lt = parse_time(r[idx["留资时间"]])
        dy = r[idx["抖音号"]]
        dy = str(dy).strip() if dy is not None and str(dy).strip() else None
        phone_raw = r[idx["电话"]]
        phone = str(phone_raw).strip() if phone_raw is not None and str(phone_raw).strip() else None
        wx = r[idx["微信"]]
        wx = str(wx).strip() if wx is not None and str(wx).strip() not in ("", "--") else None
        out.append({
            "seq": r[idx["序号"]],
            "name": str(r[idx["姓名/昵称"]]).strip(),
            "douyin_id": dy,
            "phone": phone,
            "phone_clean": clean_phone(phone_raw),
            "wechat": wx,
            "region": str(r[idx["归属地"]]).strip() if r[idx["归属地"]] else None,
            "source": str(r[idx["来源"]]).strip() if r[idx["来源"]] else None,
            "intent": str(r[idx["意向"]]).strip() if r[idx["意向"]] else None,
            "sheet_status": str(r[idx["状态"]]).strip() if r[idx["状态"]] else None,
            "lead_time": lt,
            "lead_time_str": lt.strftime("%Y-%m-%d %H:%M:%S") if lt else None,
        })
    # 按留资时间升序处理，同一人的重复行以最新一条为准
    out.sort(key=lambda x: x["lead_time"] or datetime.min)
    return out


def plan_sync(rows, existing):
    """比对 Excel 行与库内已有线索，返回 (新增, 更新, 跳过, 无法去重)。
    更新项为 (excel行, 库内行)，只改表格字段。"""
    dy_map = {r["douyin_id"]: r for r in existing if r.get("douyin_id")}
    ph_map = {r["phone_clean"]: r for r in existing if r.get("phone_clean")}
    inserted, updated, skipped, no_key = [], [], [], []
    for r in rows:
        if not r["douyin_id"] and not r["phone_clean"]:
            no_key.append(r)
            continue
        lead = dy_map.get(r["douyin_id"]) if r["douyin_id"] else None
        if lead is None and r["phone_clean"]:
            lead = ph_map.get(r["phone_clean"])
        if lead is None:
            inserted.append(r)
            continue
        db_lt = parse_time(lead.get("lead_time"))
        if r["lead_time"] and db_lt and r["lead_time"] > db_lt:
            updated.append((r, lead))
        else:
            skipped.append(r)
    return inserted, updated, skipped, no_key


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--excel", default=DEFAULT_EXCEL)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = read_excel(args.excel)
    print(f"Excel 共 {len(rows)} 行数据")

    client = Client()
    no_creds = not (os.environ.get("LEADS_SYNC_EMAIL")
                    and os.environ.get("LEADS_SYNC_PASSWORD"))
    if args.dry_run:
        print("[dry-run] 只打印计划，不写库")
        existing = None
        # dry-run 时仍需登录读库才能比对；没给凭证时只做 Excel 自检
        if no_creds:
            print("  未给凭证，仅做 Excel 自检")
        else:
            try:
                _retry(client.login, "login")
                existing = fetch_existing(client)
            except Exception as e:
                print(f"  无法读库（{e}），请重跑")
                return 1
    else:
        if no_creds:
            print("缺少登录凭证：请设置环境变量 LEADS_SYNC_EMAIL 和 LEADS_SYNC_PASSWORD")
            return 1
        email = _retry(client.login, "login")
        print(f"已登录：{email}")
        existing = fetch_existing(client)

    if existing is None:
        print(f"Excel 最新留资时间：{max((r['lead_time_str'] for r in rows if r['lead_time_str']), default='无')}")
        print("（未连库，无法判断新增/更新；请配好凭证后重跑）")
        return 0

    print(f"库里已有 {len(existing)} 条")
    inserted, updated, skipped, no_key = plan_sync(rows, existing)

    print(f"计划：新增 {len(inserted)} 条，更新表格字段 {len(updated)} 条，"
          f"跳过（无更新） {len(skipped)} 条，无法去重跳过 {len(no_key)} 条")
    for r in inserted:
        print(f"  + 新增：{r['name']}（{r['douyin_id'] or r['phone_clean']}）留资 {r['lead_time_str']}")
    for r, lead in updated:
        print(f"  ~ 更新：{r['name']} 留资 {lead.get('lead_time')} -> {r['lead_time_str']}（只改表格字段）")
    for r in no_key:
        print(f"  ! 跳过（无抖音号无完整电话）：{r['name']} 序号 {r['seq']}")

    if args.dry_run or (not inserted and not updated):
        return 0

    ok_i = ok_u = 0
    for r in inserted:
        new_row = {k: r.get(k) for k in SHEET_FIELDS}
        new_row.update({
            "seq": r["seq"],
            "follow_status": "待联系",
            "first_seen_date": datetime.now().strftime("%Y-%m-%d"),
            "pinned": False,
            "follow_logs": [],
        })
        try:
            _retry(lambda: client._req(
                "POST", "/rest/v1/leads", body=[new_row],
                extra_headers={"Prefer": "return=minimal"}),
                f"插入 {r['name']}")
            ok_i += 1
        except Exception as e:
            print(f"  插入失败 {r['name']}: {e}")
    for r, lead in updated:
        patch = {k: r.get(k) for k in SHEET_FIELDS}
        try:
            _retry(lambda: client._req(
                "PATCH", "/rest/v1/leads",
                params={"id": f"eq.{lead['id']}"}, body=patch,
                extra_headers={"Prefer": "return=minimal"}),
                f"更新 {r['name']}")
            ok_u += 1
        except Exception as e:
            print(f"  更新失败 {r['name']}: {e}")
    print(f"完成：新增 {ok_i}/{len(inserted)}，更新 {ok_u}/{len(updated)}")
    return 0 if ok_i == len(inserted) and ok_u == len(updated) else 1


if __name__ == "__main__":
    sys.exit(main())
