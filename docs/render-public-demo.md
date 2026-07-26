# Render 公网演示部署

本项目的 Render 部署是**只读研究演示版**：前端和 FastAPI 后端运行在同一个网址，使用 `research_pit` 研究模式。它不是实时行情、正式 PIT、投资建议或交易服务。

## 一次部署

1. 登录 [Render](https://dashboard.render.com/)，选择 **New + → Blueprint**。
2. 连接 GitHub，并选择本仓库的 `main` 分支。
3. Render 会识别根目录的 [`render.yaml`](../render.yaml)，确认创建 `a-share-research-workbench` 服务。
4. 点击 **Apply**，等待 Docker build 完成；完成后 Render 会提供 `https://…onrender.com` 公网地址。

无需手工填写数据库、密钥或 API Key：`render.yaml` 会生成服务端密钥。不要把个人模型 API Key 放到 Render 的公共演示环境中。

## 演示边界

- 服务以 `INVESTMENT_RESEARCH_ENV=demo` 启动，正式授权模式仍保持 blocked。
- 公网演示禁用后台调度、访问者 API Key 保存和用户触发的大模型调用，避免共享环境产生费用或泄露密钥。
- 免费 Render Web Service 会在空闲后休眠，首次重新访问可能需要等待启动；其本地磁盘是临时的，因此登录账户、缓存和本地 SQLite 数据不应视为持久资产。
- 研究数据、训练产物和 Shadow 结果应继续在本地可复现流程中生成。若要展示一个固定研究快照，请在部署前以经过审阅的只读快照方式提供，而不要在公网服务中自动抓取或训练。

## 本地验证镜像

```bash
docker build -t a-share-research-workbench .
docker run --rm -p 10000:10000 \
  -e INVESTMENT_RESEARCH_ENV=demo \
  -e INVESTMENT_RESEARCH_PUBLIC_DEMO=true \
  -e INVESTMENT_RESEARCH_SCHEDULER_ENABLED=false \
  -e INVESTMENT_RESEARCH_SECRET_KEY=replace-with-a-long-random-value \
  -e INVESTMENT_RESEARCH_CREDENTIAL_MASTER_KEY=replace-with-a-long-random-value \
  a-share-research-workbench
```

打开 `http://127.0.0.1:10000`。当需要完整数据、训练或自己的 LLM Key 时，请使用本地开发方式运行，而不是公共演示服务。
