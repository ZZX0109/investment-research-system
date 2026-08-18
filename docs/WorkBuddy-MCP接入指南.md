# WorkBuddy MCP 接入指南

本项目可作为腾讯 WorkBuddy 的只读研究连接器使用。它让 WorkBuddy 查询已冻结的 A 股研究结果、数据质量、Shadow 前向验证和金融知识库；不会训练模型、修改研究规则、发布模型或产生交易指令。

## 1. 启动服务

本机开发时启动平台：

```bash
python3 scripts/start_research_platform.py
```

公网使用时，应将平台部署到 HTTPS 域名。不要把本机 `127.0.0.1` 地址直接给远程 WorkBuddy 使用。

## 2. 创建连接令牌

登录工作台，点击顶部 `MCP`：

1. 输入连接名称；
2. 点击“生成连接令牌”；
3. 立即复制令牌。令牌只显示一次，平台只保存其不可逆 hash；
4. 如有泄露风险，在相同窗口点击“撤销”，再创建新令牌。

## 3. 在 WorkBuddy 中配置

在 WorkBuddy 的 MCP/连接器设置中新建自定义 MCP：

```json
{
  "url": "https://YOUR-DOMAIN/api/v1/workbuddy/mcp",
  "headers": {
    "Authorization": "Bearer irwb_你的连接令牌"
  }
}
```

本地联调可将 URL 替换为：

```text
http://127.0.0.1:8000/api/v1/workbuddy/mcp
```

若 WorkBuddy 使用本地桌面客户端，确认其允许访问本机服务；远程 WorkBuddy 必须使用 HTTPS 地址。

## 4. 可用工具

- `get_research_overview`：查询数据更新、生命周期、研究主模型状态与阻断原因；
- `get_asset_research`：读取一个已配置研究对象的四任务结果、数据质量和 abstain 原因；
- `compare_research_assets`：比较两个已配置对象的冻结研究结果；
- `get_price_trend`：读取最近 90 个交易日的延迟日线趋势和回撤；
- `get_shadow_performance`：读取不可变 Shadow 的冻结与回填进度；
- `search_financial_knowledge`：检索带来源、时间和版权边界的知识条目。

所有工具均为只读；未配置的证券、缺失快照和无效数据不会生成补造的概率，而会返回 `unavailable` 与具体原因。

## 5. 安全与研究边界

- 连接令牌独立于网页登录密码和用户配置的 LLM API Key；
- 每个连接按 scope 限权并可随时撤销；
- MCP 输出固定标识 `research_pit / research_only / deployment_ready=false`；
- 新闻与研报仅保留许可范围内的标题、摘要、链接及时间；完整文本仅来自官方公开文件或用户主动上传；
- 输出用于研究解释，不构成投资建议或实盘交易指令。
