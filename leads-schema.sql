-- 线索跟进 · leads 表
-- 用法：等 Supabase 项目恢复（点 Resume）后，在 Supabase 控制台
-- SQL Editor 里粘贴整段执行一次即可。执行完再跑 upload-seed.py 导数据。
-- 表只对登录用户开放（authenticated），未登录（anon）读不到任何数据。

create table if not exists public.leads (
  id uuid primary key default gen_random_uuid(),
  space_id int unique,               -- Muse 空间里的线索 id（用于溯源；新线索为空）
  seq int,                           -- Excel / 空间里的序号
  name text not null,                -- 抖音名/昵称
  douyin_id text unique,             -- 抖音号（按人去重的键之一；空值不参与唯一约束）
  phone text,                        -- 电话原文（含打码/未留标记）
  phone_clean text,                  -- 完整 11 位手机号（可拨打可去重；打码/未留时为空）
  wechat text,                       -- 微信号
  customer_name text,                -- 客户姓名（备注栏一）
  wechat_name text,                  -- 微信名（备注栏二）
  remark text,                       -- 备注（其他说明）
  follow_status text not null default '待联系',  -- 待联系/已联系/已带看/已成交/无意向
  sheet_status text,                 -- 表格里的状态原文（如“待分配、待联系”）
  intent text,                       -- 意向/需求
  region text,                       -- 归属地
  source text,                       -- 来源
  first_seen_date date,              -- 首次入库日期
  lead_time timestamptz,             -- 留资时间
  next_follow_up date,               -- 下次跟进日期
  pinned boolean not null default false,
  follow_logs jsonb not null default '[]'::jsonb,  -- 跟进记录 [{id, note, created_at}]
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists leads_lead_time_idx on public.leads (lead_time desc);
create index if not exists leads_phone_clean_idx on public.leads (phone_clean);
create index if not exists leads_pinned_idx on public.leads (pinned);

-- 更新时间自动刷新
create or replace function public.leads_set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists leads_updated_at on public.leads;
create trigger leads_updated_at
before update on public.leads
for each row execute function public.leads_set_updated_at();

-- 行级安全：只有登录用户能读写；未登录什么都看不到
alter table public.leads enable row level security;

drop policy if exists "leads_all_authenticated" on public.leads;
create policy "leads_all_authenticated"
on public.leads for all
to authenticated
using (true)
with check (true);
