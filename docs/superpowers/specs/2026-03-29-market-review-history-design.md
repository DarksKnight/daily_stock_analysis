# 大盘复盘完整入库与同日替换设计

## 背景

当前大盘复盘链路已经会将部分结构化快照写入数据库：

- `market_daily_stats`：保存当日市场涨跌统计与成交额
- `market_sector_snapshot`：保存当日板块领涨/领跌快照
- `sector_limit_stats`：保存板块涨跌停统计

但完整的大盘复盘结果仍只返回给调用方并保存为 Markdown 文件，没有专门的数据库归档表。因此存在两个问题：

1. 无法在数据库中完整追溯某天实际生成过的大盘复盘正文与其生成上下文
2. 当天重复执行复盘时，旧的完整复盘结果不会被统一替换

本设计只解决“大盘复盘完整入库”和“同日成功执行后替换旧复盘”两个目标，不扩展个股分析历史、不改动现有通知与文件保存逻辑。

## 目标

- 新增专用表 `market_review_history`，保存完整大盘复盘归档
- 每条归档至少包含：
  - 所属自然日
  - 实际市场区域 `region`
  - 最终生成的 Markdown 报告
  - 生成时使用的结构化 `overview`
  - 生成时使用的新闻列表 `news`
- 当天重复执行大盘复盘时：
  - 只有本次至少生成出一条新复盘后，才会替换旧数据
  - 替换按“自然日”进行，不区分 `region`
  - 替换语义为：删除当天所有旧复盘，再写入本次新生成的全部复盘记录
- 保持现有 `market_daily_stats`、`market_sector_snapshot`、`sector_limit_stats` 的职责不变

## 非目标

- 不改动现有个股分析历史 `analysis_history`
- 不新增 market review 列表/详情 API
- 不改变现有 Web 页面轮询与展示协议
- 不重构 `MarketAnalyzer` 现有生成逻辑
- 不新增独立迁移框架，继续沿用当前 `storage.py` 的轻量迁移模式

## 方案选择

### 方案 A：复用 `analysis_history`

不采用。

原因：

- `analysis_history` 语义是个股分析历史，不适合承载市场复盘
- 需要伪造 `code`、`query_id`、`report_type` 等字段，容易污染现有历史查询和回测逻辑
- 会增加后续维护成本和误用风险

### 方案 B：新增 `market_review_history` 专表

采用本方案。

原因：

- 与现有 `market_daily_stats`、`market_sector_snapshot` 同属市场复盘领域，职责边界清晰
- 能独立表达 `trade_date + region + report_markdown + overview_json + news_json`
- 更容易实现“同日整批替换”的语义，避免影响个股历史链路

## 数据模型

在 `src/storage.py` 中新增 ORM 模型 `MarketReviewHistory`：

- `id: Integer`，自增主键
- `trade_date: Date`，复盘所属自然日，建立索引
- `region: String(8)`，实际市场区域，取值 `cn` / `hk` / `us`
- `report_markdown: Text`，最终生成的完整 Markdown 报告
- `overview_json: Text`，`MarketOverview` 的 JSON 快照
- `news_json: Text`，生成时使用的新闻列表 JSON
- `created_at: DateTime`，写入时间

索引建议：

- `Index("ix_market_review_history_date", "trade_date")`
- `Index("ix_market_review_history_date_region", "trade_date", "region")`

这里不增加唯一约束来表达“同日单 region 唯一”，因为本设计的幂等策略由事务性“删除当天全部旧记录后再批量插入新记录”保证，不依赖逐行 upsert。

## 模块职责

### `src/storage.py`

负责：

- 定义 `MarketReviewHistory` 表
- 通过 `Base.metadata.create_all()` 自动建表
- 提供新的数据库方法

新增方法：

- `replace_market_review_history_for_date(trade_date: date, records: List[Dict[str, Any]]) -> int`
  - 在一个事务中执行
  - 先删除 `trade_date` 当天全部 `MarketReviewHistory`
  - 再批量插入本次新记录
  - 返回实际写入条数
- `get_market_review_history(trade_date: Optional[date] = None, region: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]`
  - 用于测试和后续仓储层复用
- `delete_market_review_history_for_date(trade_date: date) -> int`
  - 供仓储层或测试调用

### `src/repositories/market_review_repo.py`

在保留现有“板块热点趋势统计”和“前一日统计查询”职责的前提下，扩展为完整的大盘复盘仓储层。

新增方法：

- `replace_daily_reviews(trade_date: date, records: List[Dict[str, Any]]) -> int`
- `list_reviews(trade_date: Optional[date] = None, region: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]`

仓储层负责把上层传入的 Python 对象转换成存储层所需的 `dict/json` 结构，不让控制层直接操作 ORM。

### `src/market_analyzer.py`

`MarketAnalyzer.run_daily_review()` 继续负责：

- 采集市场数据
- 搜索新闻
- 生成 Markdown 复盘

新增行为：

- 在实例上挂载本次生成时使用的上下文，至少包含：
  - `self._last_overview`
  - `self._last_news`

这样控制层在拿到 `report` 后可以统一完成持久化，而不需要重新执行搜索或生成。

不在 `MarketAnalyzer` 中做任何“删除旧数据”动作，避免多区域执行过程中出现先删后失败的中间态。

### `src/core/market_review.py`

这里是本次改动的主控制层。

新增职责：

- 对每个实际执行的 region 收集：
  - `region`
  - `report`
  - `overview`
  - `news`
- 仅当本次至少成功生成一条新复盘时，才调用 repository 执行整日替换

控制逻辑：

1. 单区域模式：
   - 生成 1 条复盘记录
   - 若成功，则替换当天全部旧记录并写入这 1 条新记录
2. 多区域模式 `both/all`：
   - 逐个区域生成复盘
   - 汇总所有成功生成的记录
   - 若成功记录数大于 0，则在一个事务中：
     - 删除当天全部旧记录
     - 插入本次成功生成的全部 region 记录

这样可以保证：

- 生成失败时不会删除旧数据
- 生成成功后，同一天数据库中只保留最后一次成功执行的那一批复盘
- `both/all` 不需要额外保存一条 `region=both/all` 的聚合记录，数据库中只保存真实市场区域记录

## 数据流

### 单区域

1. `run_market_review()` 创建 `MarketAnalyzer(region=<cn|hk|us>)`
2. `MarketAnalyzer.run_daily_review()` 生成 `report`
3. `MarketAnalyzer` 将 `overview/news` 挂载到实例
4. `run_market_review()` 组装待持久化记录
5. repository 在事务中删除当天所有旧 `market_review_history`
6. repository 写入新的单条记录
7. 控制层继续执行现有的文件保存与通知逻辑

### 多区域

1. `run_market_review()` 逐个 region 执行 `MarketAnalyzer.run_daily_review()`
2. 每个成功 region 生成一条待持久化记录
3. 若成功记录为空，则跳过替换，保持旧数据不变
4. 若成功记录非空，则 repository 在一个事务中：
   - 删除当天全部旧 `market_review_history`
   - 批量写入本次所有成功 region 记录
5. 控制层拼接现有对外返回的 Markdown 文本，并继续文件保存/通知逻辑

## JSON 序列化约定

### `overview_json`

保存 `MarketOverview` 的结构化快照，建议使用 `dataclasses.asdict()` 生成基础字典，再做必要的兼容清洗，确保以下内容可追溯：

- `date`
- `indices`
- `hk_indices`
- `up_count` / `down_count` / `flat_count`
- `limit_up_count` / `limit_down_count`
- `non_st_limit_up_count` / `non_st_limit_down_count`
- `total_amount`
- `prev_total_amount` / `prev_review_date`
- `amount_ratio` / `volume_status`
- `rise_fall_status`
- `market_condition` / `can_buy`
- `top_sectors` / `bottom_sectors`
- `all_top_sectors` / `all_bottom_sectors`
- `top_sectors_by_limit_up` / `top_sectors_by_limit_down`
- `top_concept_sectors` / `bottom_concept_sectors`
- `top_concept_by_limit_up`

### `news_json`

保存生成复盘时实际参与的新闻列表，优先保留：

- `title`
- `snippet`
- `url`
- `source`
- `published_date`

如果新闻对象是带属性的搜索结果对象，应在 repository 或控制层统一转换为 JSON 可序列化字典。

## 失败处理

- 单个 region 生成失败：
  - 记录日志
  - 不纳入本次替换批次
- 多区域模式下部分 region 失败：
  - 只要有至少 1 个 region 成功，就以“本次成功子集”替换当天全部旧记录
  - 这是本次已确认的业务语义
- 本次所有 region 全部失败：
  - 不删除旧数据
  - 按现有逻辑返回 `None` 或空报告
- 数据库写入失败：
  - 记录错误日志
  - 不影响已有文件保存与通知的主流程返回
  - 但应确保替换使用单事务，避免“已删旧数据但新数据未写完”的中间态

## 测试设计

### 存储层测试

新增测试覆盖：

- `replace_market_review_history_for_date()` 首次写入成功
- 同日再次替换时，旧记录被整日删除，新记录正确保留
- 替换按自然日生效，不区分旧记录的 `region`
- 指定日期查询和 region 查询返回正确结果

### 仓储层测试

新增测试覆盖：

- `MarketReviewRepository.replace_daily_reviews()` 能正确调用存储层并完成 JSON 序列化
- `overview/news` 中存在列表和嵌套字典时仍可正确落库

### 控制层测试

新增测试覆盖：

- 单区域成功时会写入 1 条历史记录
- `both/all` 成功时会写入多条真实 region 记录
- 多区域部分成功时，仅写入成功子集，并清空当天全部旧记录
- 本次完全失败时不会删除当天旧记录

### 回归验证

至少执行：

- `python -m py_compile <changed_python_files>`
- 相关 pytest 用例

如实现落在纯后端层，可优先跑针对性测试文件，而不是默认触发前端构建。

## 兼容性与风险

兼容性：

- 不修改现有 API 请求/响应结构
- 不修改现有 Web 页面轮询协议
- 不改变 `market_daily_stats` 和 `market_sector_snapshot` 的现有读写语义

主要风险：

- `MarketOverview` 或新闻对象中含非 JSON 可序列化字段，需在写库前统一转换
- 多区域模式使用“成功子集替换整日旧数据”后，当天历史可能不再包含之前成功过但本次失败的 region；这是本次已明确接受的业务规则
- 如果未来增加 market review 历史查询 API，需要定义返回哪一层 JSON 结构以及是否暴露完整 Markdown

## 实施范围

本次实施预计只修改以下范围：

- `src/storage.py`
- `src/repositories/market_review_repo.py`
- `src/market_analyzer.py`
- `src/core/market_review.py`
- `tests/` 下对应新增或更新的后端测试
- `docs/CHANGELOG.md`

## 回滚策略

若功能上线后需要回滚：

1. 回退本次代码变更
2. 保留数据库中新建的 `market_review_history` 表即可，不要求删除表
3. 回滚后系统仍可继续使用既有 `market_daily_stats` 与 `market_sector_snapshot` 逻辑，不影响其他主链路

## 结论

采用新增 `market_review_history` 专表方案，在 `src/core/market_review.py` 的总控层统一收集结果并在“本次至少成功生成一条新复盘”后执行事务性整日替换。

这样可以用最小范围改动补齐：

- 完整复盘入库
- 同日重复执行后旧复盘清理
- 多区域复盘的真实 region 归档
- 失败时保留旧数据的安全语义
