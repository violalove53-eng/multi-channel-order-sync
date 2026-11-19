# 订单同步项目规格（GitHub Project for Replit 面试）

_定稿 2026-11-18。范围：只做订单同步这一件事。_

## 一句话

把 TikTok Shop（约 700 单）和 Shopify 独立站的订单，同步进一个自己的统一订单库 —— 管道做扎实，功能先不做。

## 为什么是这个项目

- 数据是真的：700 单是自己店里跑出来的，不是造的假数据
- 形状是对的：多源接入、schema 映射、幂等、水位线 —— 全是 Connectors / 平台后端岗的日常
- 故事是现成的：每个被砍掉的功能都有数据层面的理由（见文末"面试故事"）

## 范围

**做：**
- TikTok 订单导入（v1 用卖家中心导出的 CSV；连接器接口按标准形态设计，资质下来可换真 API）
- Shopify 订单同步（GraphQL API 真连接，订单量小，先用它把管道练通）
- 统一订单模型 + 两份 schema 映射
- 幂等写入、增量水位线、失败重试 + 死信、同步运行日志

**不做（明确砍掉，理由见文末）：**
- 防超卖自动下架 —— 价格链接订单不带商品身份，无从匹配
- 合单、对账 —— TikTok 卖家中心原生自带，不重复造
- 报表 / 场次分析 —— v2 再说，先把管道做完

## 架构

```
TikTok CSV ──► Connector(TikTok) ──┐
                                    ├──► Normalize(schema 映射) ──► 幂等 Upsert ──► 订单库 (Postgres)
Shopify API ─► Connector(Shopify) ─┘                                        │
                                                              sync_runs 日志 / failed_records 死信
```

- **Connector 接口**统一抽象：`fetchOrders(since watermark) -> 原始订单列表`。TikTok 实现读 CSV，Shopify 实现调 GraphQL，上层不感知差异
- **Normalize**：每个平台一份映射表，翻成统一模型；原始报文整包存 `raw_payload` 留底，映射错了可重放
- **存储**：Postgres（起步可用 SQLite，里程碑 2 前换掉）

## 统一订单模型（canonical schema）

| 字段 | 说明 |
|---|---|
| `source` | `tiktok` / `shopify` |
| `source_order_id` | 平台原始订单号 |
| `buyer_name` | 买家昵称 |
| `status` | 统一枚举：`UNPAID / PAID / SHIPPED / DELIVERED / CANCELLED / REFUNDED`，各平台状态词映射进来 |
| `total_amount` | 统一用分（整数）存，避免小数精度问题 |
| `currency` | USD |
| `price_tier` | 价格档（4.99 / 6.99 / …），TikTok 价格链接模式特有，保留原始档位 |
| `created_at / paid_at / shipped_at` | 时间戳，统一 UTC |
| `raw_payload` | 平台原始数据 JSON 留底 |

唯一键：`(source, source_order_id)`。

## 三个核心机制

**1. 幂等（idempotent）**
- 按唯一键 upsert：记录不存在 → 插入；存在且无变化 → 跳过；存在且带更新 → 覆盖
- **状态防倒退**：状态机只许前进（`PAID → SHIPPED → DELIVERED`），迟到的旧数据不许把"已发货"覆盖回"待发货"；`CANCELLED / REFUNDED` 为终态
- 验收标准：同一批数据连跑 3 遍，行数与内容分毫不差

**2. 水位线（watermark）**
- 每个连接器一行水位线记录：`last_synced_at`
- 每次只拉水位线之后的数据；**故意回退 15 分钟重叠**防边界漏单，重叠的重复靠幂等兜底
- 水位线只在一整批全部写成功后才推进；中途崩了，下次从原水位线重拉

**3. 失败处理**
- 单条失败不拖垮整批：进 `failed_records` 死信表（原始数据 + 错误原因），其余照常同步
- API 侧失败：指数退避重试（Shopify 限流按其返回的节流信号走）
- 每次同步写一条 `sync_runs`：开始/结束时间、拉取数、新增数、跳过数、更新数、失败数 —— 这是将来面试报数字的来源

## 里程碑（按周末计）

- **W1 — Shopify 打通**：GraphQL 拉单 → 映射 → 幂等入库 → 水位线增量。量小，专练管道
- **W2 — TikTok 全量**：从卖家中心导出订单 CSV（拿到样本后按真实列名定稿第二份映射表），700 单导入，行数对账
- **W3 — 健壮性**：死信 + 重试 + sync_runs 日志；做三遍重跑幂等验收、断点续跑验收
- **W4 — 产出物**：README（架构图 + 三个核心机制各一段）+ 30 秒演示 + 数字整理

## 技术选型

- 语言：Java（十年存量，速度优先）；想顺带练面试语言的话 Go 亦可，项目重点不在语言
- DB：Postgres；部署：最终把演示部署到 Replit 上
- 不做前端；最多一个极简的同步状态页（读 sync_runs）

## 面试弹药清单（W4 整理）

**要跑出的数字：**总订单数（700+）、重复拦截数（重跑时跳过多少）、单次全量同步耗时、两份映射表各映射了多少字段。

**要会讲的故事：**
1. 为什么砍掉防超卖 —— 价格链接订单不带商品身份，功能边界由数据模型决定
2. 为什么 TikTok 用 CSV —— 开放 API 的资质现实；连接器接口按可替换设计，资质下来只换实现层
3. 幂等的那句英文 —— "The sync is idempotent: every order is keyed by a unique ID, and when the same order arrives again, we either skip it if nothing changed, or upsert it if it carries a newer state."
