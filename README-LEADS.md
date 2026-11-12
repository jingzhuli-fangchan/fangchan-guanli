# 线索跟进 · 独立网站

普通浏览器直接打开，不用挂 VPN。挂在房产工作台下面：
**https://jingzhuli-fangchan.github.io/fangchan-guanli/leads.html**

## 文件说明

| 文件 | 说明 |
|---|---|
| `leads.html` | 线索跟进页面（登录门 + 列表 + 跟进/备注/置顶/删除） |
| `leads-schema.sql` | Supabase `leads` 表结构 + RLS（只登录用户可读写） |
| `sbclient.py` | Supabase 最小客户端（只用 Python 标准库） |
| `upload-seed.py` | 一次性导入：把空间里的 79 条线索导进 Supabase |
| `sync-excel-to-supabase.py` | 增量同步：抖音来客线索表.xlsx -> Supabase |
| `index.html` | 工作台首页（已加“线索跟进”入口） |

种子数据在 `~/workspace/goals/goal-7/hidden_files/leads-seed-2026-11-12.json`
（79 条：抖音 31 条 + 2025 年旧客户 48 条，含客户完整电话，**绝不要放进仓库**）。

## 上线步骤（按顺序，Supabase 恢复后）

1. **恢复 Supabase**：用户本人在 Supabase 控制台点 Resume（免费项目因 7 天无活动被暂停，只有他能恢复）。
2. **建表**：在 Supabase SQL Editor 里执行 `leads-schema.sql`（整段粘贴，运行一次）。
3. **建账号**：在 Supabase 控制台 Authentication > Users 里建一个用户（邮箱+密码），或在工作台首页点“注册”建一个。和工作台同一个账号体系，leads 页面用同一个账号登录。
4. **导数据**：在本机跑
   ```
   LEADS_SYNC_EMAIL=xxx@xxx LEADS_SYNC_PASSWORD='...' python3 upload-seed.py
   ```
   79 条全量导入，已存在的自动跳过（可重复跑，不会重复插）。
5. **部署**：把本仓库推到 GitHub（见下），GitHub Pages 已开启，1-2 分钟后页面上线。
6. **验证**：手机浏览器打开 `https://jingzhuli-fangchan.github.io/fangchan-guanli/leads.html`，
   登录后应看到 79 条线索；改一条状态、刷新页面还在，就说明读写都通了。

## 部署（推到 GitHub）

```bash
cd ~/workspace/fangchan-guanli
git init
git add index.html leads.html leads-schema.sql sbclient.py upload-seed.py sync-excel-to-supabase.py README-LEADS.md
git commit -m "新增线索跟进独立页面（leads.html）"
git remote add origin https://github.com/jingzhuli-fangchan/fangchan-guanli.git
git push -u origin main
```

没有本机 token 时，改用 GitHub 网页端：打开仓库 → Add file → Upload files，
把上面 7 个文件拖进去提交即可（index.html 选“替换”）。Pages 会自动重新发布。

## 每天同步新线索（需新建一个定时任务）

现有每晚 21:05 的任务是 Excel -> Muse 空间同步，**不要动它**。
新增一个每天 21:10 跑的任务（在 21:05 之后，确保 Excel 已是最新）：

```
LEADS_SYNC_EMAIL=xxx@xxx LEADS_SYNC_PASSWORD='...' \
  python3 ~/workspace/fangchan-guanli/sync-excel-to-supabase.py
```

同步规则：只追加新于库内最新留资时间的线索；按人去重（同一抖音号或同一完整电话算同一人）；
已存在的人只在留资时间更新时才刷新表格字段；**绝不覆盖**跟进状态、跟进记录、备注、置顶、下次跟进日期。
跑之前可先加 `--dry-run` 看一眼计划。

## 登录方式

- Supabase Auth 邮箱+密码，单用户（和工作台同一个账号）。
- 未登录看不到任何数据（RLS：anon 无权读写）。
- 密码不写在任何文件里；账号密码由家长走安全方式交给用户。
- 恢复前页面打不开/登录失败是正常的：登录页有提示，恢复后刷新再试。

## 注意

- 网站本身不依赖 VPN；Supabase 在境外，但 GitHub Pages + Supabase 都是公开可达的，
  国内浏览器直接打开即可。
- 网站上的改动（状态/记录/备注/置顶）只存在 Supabase 里，**不会反向同步回 Muse 空间**；
  空间仍由每晚 21:05 的 Excel 同步继续喂新线索。两边以 Excel 为共同上游。
- 种子 JSON 和脚本里的密码/邮箱一律不要提交进仓库。
