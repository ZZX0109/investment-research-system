# 项目目录说明

版本时间: 2026-07-02

## 目录结构

```text
investment-research-system/
  README.md                         项目总说明、启动方式、能力概览
  package.json                      前端脚本与整体验证脚本
  tsconfig.json                     TypeScript 配置
  backend/
    app.py                          FastAPI 后端、SQLite 数据层、投研工作流 API
    requirements.txt                Python 依赖
  ml/
    data/                           点时数据集构建、真实数据 ingest、质量报告、时间切分和 synthetic smoke 数据
    features/                       行情特征与风险标签
    models/                         表格基线、CNN/TCN、PatchTST、iTransformer、情景编码器
    risk/                           风险分布引擎、VaR breach 和高风险 regime 判断
    training/                       训练入口、模型注册、评估与校准
    inference/                      推理、相似情景检索和 SQLite 导出
    pipelines/                      minimal_demo、real_data_v1 与 reliable scale 训练 pipeline
    reporting/                      Agent token 压缩报告
    tests/                          ML 点时、切分、标签和推理合约测试
  frontend/
    index.html                      Vite 前端入口
    src/
      main.tsx                      React 主界面
      sampleData.ts                 前端类型与 fallback 数据
      styles.css                    页面样式
      vite-env.d.ts                 Vite 类型声明
  docs/
    frontier-research-pain-points.md 前沿研究痛点与论文来源
    harness-loop-engineering-development-plan.md Harness/Loop Engineering 开发计划
    deep-learning-execution-plan.md  深度学习时序模型执行计划
    algorithm-training-runbook.md    最小 demo 与一定规模算法训练步骤
    project-02-gap-audit.md          与 AI 测试官蓝图的差距审计
    project-structure.md             当前文件
  scripts/
    verify.sh                       一键构建和核心接口验证
  data/
    investment_research.sqlite3               本地 SQLite 缓存，运行时生成，不提交
```

## 常用命令

```bash
npm install
python3 -m pip install -r backend/requirements.txt
npm run dev:api
npm run dev -- --port 5173
npm run verify
npm run train:real:smoke
npm run train:real
python3 -m ml.pipelines.reliable_scale --fetch-real --universe large_us_cn --min-symbols 300 --min-samples 12000 --min-rows 1250
```

## 主要接口

- `GET /api/health`
- `POST /api/auth/register`
- `POST /api/auth/login`
- `GET /api/auth/me`
- `POST /api/onboarding`
- `GET /api/api-keys`
- `POST /api/api-keys`
- `GET /api/portfolio`，需要 Bearer Token
- `GET /api/research/{symbol}`，需要 Bearer Token
- `POST /api/documents/{symbol}/analyze`，需要 Bearer Token
- `GET /api/reports/{symbol}.md`，需要 Bearer Token
- `GET /api/ml/models`，需要 Bearer Token
- `POST /api/ml/datasets/build`，需要 Bearer Token
- `POST /api/ml/train`，需要 Bearer Token
- `POST /api/ml/infer/{symbol}`，需要 Bearer Token
- `GET /api/ml/predictions/{symbol}`，需要 Bearer Token
- `GET /api/ml/scenarios/{symbol}`，需要 Bearer Token
- `GET /api/ml/token-compression/{symbol}`，需要 Bearer Token
- `POST /api/settings/report`，需要 Bearer Token
- `POST /api/refresh/daily`，需要 Bearer Token

## 整理原则

- 前端代码统一放在 `frontend/`。
- 后端代码统一放在 `backend/`。
- 研究文档和评审材料统一放在 `docs/`。
- 可重复验证脚本放在 `scripts/`。
- 运行时数据和构建产物不进入版本管理。
