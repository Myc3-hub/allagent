# 综合性 AI 运营智能体(AllAgent)

> 一个面向客户的综合性 AI 智能体:既能科学地分析客户需求,又能直接完成实际任务
> (撰写发言稿、制作主题 PPT、报告方案、通知公告等),并生成 Word / PPT / Excel / PDF 各类交付文件。
> 所有分析严谨可溯源:引用已公布的同类数据,严禁编造数据与来源。

---

## 一、核心能力

| 能力 | 说明 |
|---|---|
| **需求分析** | 客户提出需求 → 单轮核心提问(≤3 问,直击核心)→ 结构化需求文档(5W2H 方法论)→ 确认卡(可修改)→ 选择导出文件 |
| **公开数据调研** | 内置调研模块直接检索公开网页(政府数据/行业报告/供应商案例),**零第三方搜索 API**;每条引用绑定来源 URL 与检索日期 |
| **文件生成** | 需求分析产物:Word 报告 / PPT 演示 / Excel 清单预算 / PDF 规格说明书,四类文件任选 |
| **通用任务引擎** | 识别客户的创作请求(发言稿/主题PPT/报告方案/通知公告),补充必要信息(≤2 问)后直接生成交付文件;报告/PPT 类任务自动附公开数据调研 |
| **主动建议** | 需求确认后主动告知客户可完成的延伸任务;欢迎页展示两大能力入口(需求分析 / 文件生成) |

## 二、技术架构

```
浏览器(单页聊天) --HTTP/SSE--> FastAPI --DeepSeek(OpenAI SDK)--> LLM
                                    |-- 会话存储(内存 + JSON 持久化)
                                    |-- 调研模块(公开网页抓取,零第三方API)
                                    |-- 渲染器(python-docx/pptx/openpyxl/reportlab)
                                    └-- output/{session_id}/ *.docx|pptx|xlsx|pdf
```

- **后端**:Python 3.14 + FastAPI + uvicorn(单 worker)
- **大模型**:DeepSeek `deepseek-chat`(OpenAI 兼容 API;唯一需要的密钥)
- **前端**:vanilla JS 单页应用,无构建,SSE 流式渲染
- **文件生成**:python-docx / python-pptx / openpyxl / reportlab(中文字体:微软雅黑/宋体/黑体)

## 三、工作流程(会话状态机)

```
clarify(澄清) → research(调研) → confirm(确认) ⇄ revise(修改) → choose(选择导出文件) → done(完成)
     └── 首条消息判定:创作任务 → task(任务执行) → done
```

1. **clarify 澄清阶段(单轮模式)**
   - 首条消息经 LLM 提取为结构化需求(只填客户明确表达的信息)
   - 代码按优先级判定缺失字段(P0:背景/目标/功能/预算/周期;P1:范围/使用人群/性能/安全/约束)
   - 只提**一轮**问题(≤3 个,必须覆盖全部缺失核心字段),回答后直接进入调研,未答字段由定稿阶段写入假设
2. **research 调研阶段**(约 15~40 秒,SSE 实时推送进度)
   - 代码从标题提取**核心主题词**(修饰剥离:如"XX公司员工考勤系统"→"考勤系统")
   - 必应 + 搜狗 + 百度三源检索 → 权威源排序(政府网 > 央媒 > 行业报告)→ 并发抓取正文(SSL 异常自动降级)
   - **相关性门控**:正文必须含主题词首双字,无关页面(词语释义/手机市场等)直接丢弃
   - LLM 只从抓取正文提取数据点;**来源 URL/名称/日期由代码强制回填**,LLM 返回的编造 URL 直接丢弃;同一来源最多引用 2 条
   - 检索不到就明说(记录"缺口"),绝不虚构补位;无主题词时跳过调研并明示
3. **confirm 确认阶段**
   - 一次定稿调用:补全缺失字段(全部写入 assumptions)、生成风险(≥3 条)/优先级/开放问题、350~500 字要点摘要
   - 引用仅限调研简报中的数据点(代码强制覆盖);版本号/时间戳由代码维护
   - 前端渲染确认卡:摘要 + 可折叠数据来源列表(名称+链接+检索日期)+ 折叠 JSON + [确认无误][提出修改]
4. **choose 选择导出文件阶段**
   - 智能体询问需要导出的文件(Word 报告/PPT 演示/Excel 表格/PDF 文档,可多选或"全部")
   - 代码级关键词解析(稳定可靠);未识别则重新询问;此阶段说"修改"则回到修改流程
5. **task 任务执行阶段**(通用任务引擎)
   - LLM 分类:speech(发言稿)/ ppt(主题PPT)/ report(报告方案)/ notice(通知公告)/ none(需求描述、闲聊不误判)
   - 主题缺失 → 补充提问(≤2 问,最多两轮);报告/PPT 类自动执行公开数据调研
   - 生成 IR → 渲染文件 → 聊天内文件卡片下载;完成后主动提示可继续其他任务
6. **done 完成阶段**:自由问答 + 继续识别新任务

## 四、数据严谨性设计(核心红线)

| 防线 | 机制 |
|---|---|
| 来源不可编造 | 数据点 URL 只能来自搜索/抓取元数据;LLM 输出不在白名单内的 URL 直接丢弃;引用列表由代码强制覆盖 |
| 内容不可编造 | LLM 提取只基于抓取正文,未出现的数字一律不得提取;定量论断要么引用 [ref-XX],要么显式标注"估算/假设" |
| 检索不跑题 | 代码确定性核心主题词 + 相关性门控(必须命中主题词首双字)+ LLM 候选检索词主题校验 |
| 检索不到就明说 | 调研简报记录"缺口";定稿写明"未获取到公开数据,以下为假设" |
| 价格不可编造 | Excel 预算表限"预算分配建议",强制标注"具体报价需商务确认" |
| 已有内容不可丢 | 代码级"非降级合并":LLM 合并/定稿只能新增修改,永远不能清空客户已回答的字段 |
| 结构容错 | LLM 输出常见结构错误自动修复(枚举空串→默认值、字符串列表→对象数组并编号、空串列表→空数组等) |

## 五、文件生成体系(两级流水线)

```
LLM(严格 JSON Schema + response_format=json_object)
  → IR 中间表示(Pydantic 严格校验,失败带错误重试≤2次,温度降至0.1)
  → 纯代码渲染器(零 LLM 调用,格式稳定可测)
  → 最终文件(含"参考数据与来源"节)
```

| 文件 | IR 模型 | 渲染要点 |
|---|---|---|
| Word 报告 | WordDocIR(封面+执行摘要+≤7节+表格) | A4;标题黑体/正文宋体(西文+东亚字体成对设置);要点式 ≤40 字/条;表格表头底纹;页码域;文末"参考数据与来源" |
| PPT 演示 | PptDocIR(10~14页:封面/目录/章节/内容/数字/表格/总结/来源/致谢) | 16:9 深蓝商务风;要点 ≤5 条且 ≤20 字;数字卡片;无装饰横线(避免 AI 痕迹);末页"数据来源" |
| Excel 表格 | ExcelDocIR(需求清单/预算分配/说明与假设 3 表) | 大标题合并+深蓝表头+冻结窗格;CJK 宽度列宽自适应;预算表 SUM 合计;说明页含假设与来源清单 |
| PDF 规格书 | PdfDocIR(≤8 节编号条款,含验收标准) | 微软雅黑标题/宋体正文(字体子集嵌入可移植);页眉细线+页码;封面独立页 |

**通用任务复用同一体系**:发言稿/报告/通知 → WordDocIR;主题 PPT → PptDocIR;任务文件独立记录(`task_files`),与需求分析文件互不影响。

## 六、API 设计

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/health | 健康检查 |
| POST | /api/sessions | 新建会话 |
| GET | /api/sessions | 会话列表 |
| GET | /api/sessions/{sid} | 历史消息 + 阶段 + 需求文档 + 文件记录 |
| DELETE | /api/sessions/{sid} | 删除会话(含 output 目录) |
| POST | /api/sessions/{sid}/stream | 消息入口 `{kind:"message",text}` 或修改 `{kind:"revise",comment}`,SSE 响应 |
| POST | /api/sessions/{sid}/confirm | 需求确认 → 询问导出文件 |
| POST | /api/sessions/{sid}/files/{ftype} | 生成需求文件(word/ppt/excel/pdf) |
| GET | /api/sessions/{sid}/files/{ftype}/download | 下载需求文件(中文文件名 RFC 5987) |
| GET | /api/sessions/{sid}/task-files/{index}/download | 下载任务文件 |

**SSE 事件协议**(text/event-stream):

```
meta → text(delta 逐字流) → questions(问题卡片)
     → research(started/progress/done 调研进度)
     → requirement(需求确认卡,含 references) | task_file(任务交付文件)
     → done | error(友好中文提示)
```

## 七、前端设计

- **布局**:左侧会话栏(标识/新建会话/会话列表)+ 右侧聊天区(顶部标题+阶段徽标 / 消息流 / 文件按钮区 / 输入框)
- **欢迎区**:打开页面即显示两大能力卡片(需求分析 / 文件生成,带小字说明),点击自动建会话并填入示例
- **交互**:流式打字效果、调研进度卡、需求确认卡(含数据来源折叠列表)、导出文件快捷选择条、任务文件下载卡
- **安全**:LLM 文本一律 `textContent` 渲染(防 XSS);访客 Key 仅存浏览器 localStorage,请求经 X-API-Key 头传输,服务器不落盘
- **风格**:科技风——深蓝→青渐变主色、毛玻璃卡片、光晕背景、网格底纹;首次使用弹出 Key 输入框,侧栏可随时更换 Key

## 八、运行与部署

### 本机运行

```bash
cd C:\Users\15298\projects\ai-agent
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
# .env 中填入唯一的密钥(可选,访客可自带 Key):
#   DEEPSEEK_API_KEY=sk-xxx
.venv\Scripts\python run.py
# 浏览器打开 http://127.0.0.1:8000
```

### 公网部署(Render,免费)

1. 仓库已含 `Dockerfile` 与 `render.yaml`,推送到 GitHub
2. render.com → GitHub 登录 → New → Blueprint → 选择仓库 → Apply
3. 5~10 分钟构建完成,获得 `https://ai-agent-xxx.onrender.com` 公网网址

### 访客自带 API Key 模式(公网版核心)

- 打开网页先弹窗输入使用者**自己的 DeepSeek API Key**,各用各自额度,服务器无需配置密钥
- Key 仅存于访客浏览器 localStorage,经 HTTPS 传输,服务器不落盘(sessions.json 持久化时排除)
- 服务器按 Key 缓存 LLM 客户端,多访客互不影响;无 Key 时返回友好中文提示

### 部署注意

- **依赖**:fastapi、uvicorn、python-docx、python-pptx、openpyxl、reportlab、openai、httpx、jinja2、pydantic、python-dotenv、lxml
- **会话持久化**:`data/sessions.json`,本机重启自动恢复;Render 免费实例文件系统为临时(重启清空,不影响使用)
- **中文字体**:Windows 用系统微软雅黑/宋体/黑体;Linux 自动回退到打包的思源黑体(`fonts/`,字体子集嵌入)
- **免费实例冷启动**:闲置 15 分钟后休眠,首次访问约 30~60 秒唤醒
- **v1 限制**:公开搜索抓取为尽力而为(商业部署建议接入正式搜索服务)

## 九、项目结构

```
.
├── run.py                      # 启动入口(固定单 worker)
├── requirements.txt / .env / .env.example / .gitignore / README.md
├── app/
│   ├── main.py                 # FastAPI 入口(启动时恢复会话、注册 PDF 字体)
│   ├── config.py               # .env 配置:模型、字体路径、澄清/调研参数
│   ├── tasks.py                # 通用任务注册表(发言稿/主题PPT/报告/通知)
│   ├── agent/
│   │   ├── orchestrator.py     # 状态机主循环 + 通用任务引擎(分类/提问/生成)
│   │   ├── clarify.py          # 澄清优先级规则(P0/P1 字段,纯代码确定性)
│   │   └── finalize.py         # 定稿:数据支撑的需求文档 + 要点摘要
│   ├── llm/
│   │   ├── client.py           # DeepSeek 封装:流式聊天 + json_call(清洗/校验/重试三重防线)
│   │   └── prompts.py          # 全部提示词(提取/提问/合并/检索词/数据提取/定稿/文件/任务)
│   ├── research/
│   │   ├── sources.py          # 权威源注册表(政府网/央媒/行业报告分级排序)
│   │   ├── search.py           # 必应+搜狗+百度三源搜索(尽力而为,优雅降级)
│   │   ├── fetcher.py          # 抓取:UA/超时/大小上限/编码自适应/SSL降级
│   │   └── researcher.py       # 编排:核心主题词提取/相关性门控/数据点提取(URL白名单)
│   ├── files/
│   │   ├── registry.py         # 文件类型注册表(IR/prompt/渲染器映射)
│   │   ├── render_word.py      # Word 渲染(封面/黑体标题/宋体正文/表格/页码)
│   │   ├── render_ppt.py       # PPT 渲染(16:9 深蓝商务风,编号圆块/数字卡片)
│   │   ├── render_excel.py     # Excel 渲染(合并标题/表头/冻结窗格/SUM合计)
│   │   └── render_pdf.py       # PDF 渲染(中文字体嵌入/页眉页脚/条款式)
│   ├── models/
│   │   ├── schemas.py          # RequirementDoc、field_states、Session(含容错校验器)
│   │   └── intermediates.py    # 四类文件 IR + Reference 引用模型
│   ├── api/
│   │   ├── chat.py             # 会话 CRUD、SSE 流端点、confirm、文件选择
│   │   └── files.py            # 需求文件生成/下载、任务文件下载
│   ├── store/
│   │   └── session_store.py    # 会话存储(内存 dict + Lock + JSON 持久化)
│   └── utils/
│       ├── fonts.py            # reportlab 中文字体注册、docx/pptx 东亚字体
│       └── text.py             # JSON 清洗、截断、CJK 宽度、HTML→文本、编码探测
├── static/
│   ├── index.html              # 单页(侧栏 + 聊天区 + 欢迎能力卡片)
│   ├── css/style.css           # 科技风样式(渐变主色/毛玻璃/网格底纹)
│   └── js/app.js               # 会话管理、SSE 解析、消息/卡片渲染
├── data/                       # sessions.json(运行时生成,重启恢复)
├── output/                     # 生成文件,按 {session_id}/ 分目录
└── scripts/
    └── test_renderers.py       # 渲染器自检(手写 fixture,不含 LLM)
```

## 十、关键设计决策

1. **确定性覆盖检查 + LLM 表达**:缺失字段判定由代码完成(科学不漏项),LLM 只负责提问措辞与合并
2. **两级生成流水线**:LLM → 严格校验的 IR → 纯代码渲染,格式稳定可测
3. **需求文档是唯一"记忆"**:LLM 上下文只带(需求 JSON + 调研简报 + 最近消息),控制上下文窗口
4. **代码对 LLM 的三重不信任**:不信任其枚举值(容错降级)、不信任其结构(自动修复)、不信任其来源(URL 白名单)、不信任其合并(非降级合并)
5. **宁可无数据,不可有假数据**:调研所有环节失败均优雅降级并明示缺口
