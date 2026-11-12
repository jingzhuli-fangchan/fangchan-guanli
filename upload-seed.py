#!/usr/bin/env python3
"""一次性把「线索跟进」空间里的 79 条线索导进 Supabase leads 表。

用法（在 Supabase 点 Resume、并执行 leads-schema.sql 之后）：
  LEADS_SYNC_EMAIL=xxx@xxx LEADS_SYNC_PASSWORD='...' \
      python3 upload-seed.py [--seed PATH] [--dry-run]

  --seed     种子 JSON，默认 ~/workspace/goals/goal-7/hidden_files/leads-seed-2026-11-12.json
             （种子含客户完整电话，绝不要把它放进公开仓库）
  --dry-run  只打印要插多少条，不写库

去重：按 space_id / douyin_id / 完整电话三者任一命中即视为已存在，跳过不插。
已存在的行一律不动（不覆盖状态、跟进记录、备注、置顶）。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sbclient import Client, SupabaseError

DEFAULT_SEED = os.path.expanduser(
    "~/workspace/goals/goal-7/hidden_files/leads-seed-2026-11-12.json")

# 种子字段 -> leads 表字段（space_id/seq 只做溯源）
COLUMNS = ["space_id", "seq", "name", "douyin_id", "phone", "phone_clean",
           "wechat", "customer_name", "wechat_name", "remark", "follow_status",
           "sheet_status", "intent", "region", "source", "first_seen_date",
           "lead_time", "next_follow_up", "pinned", "follow_logs"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", default=DEFAULT_SEED)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    seed = json.load(open(args.seed))
    print(f"种子共 {len(seed)} 条")

    client = Client()
    if args.dry_run:
        print("[dry-run] 不登录、不写库")
        existing = []
    else:
        email = client.login()
        print(f"已登录：{email}")
        existing = client.select_leads(columns="id,space_id,douyin_id,phone_clean")
        print(f"库里已有 {len(existing)} 条")

    have_space = {r["space_id"] for r in existing if r.get("space_id") is not None}
    have_dy = {r["douyin_id"] for r in existing if r.get("douyin_id")}
    have_phone = {r["phone_clean"] for r in existing if r.get("phone_clean")}

    to_insert, skipped = [], 0
    for row in seed:
        if (row.get("space_id") in have_space
                or (row.get("douyin_id") and row["douyin_id"] in have_dy)
                or (row.get("phone_clean") and row["phone_clean"] in have_phone)):
            skipped += 1
            continue
        to_insert.append({k: row.get(k) for k in COLUMNS})
    print(f"需新增 {len(to_insert)} 条，跳过已存在 {skipped} 条")

    if args.dry_run:
        for r in to_insert[:5]:
            print("  例：", r["name"], r.get("douyin_id"), r.get("phone_clean"))
        return 0

    ok = 0
    for r in to_insert:
        try:
            client.insert_lead(r)
            ok += 1
        except SupabaseError as e:
            print(f"  插入失败 {r['name']}: {e}")
    print(f"完成：成功 {ok}/{len(to_insert)} 条")
    return 0 if ok == len(to_insert) else 1


if __name__ == "__main__":
    sys.exit(main())
