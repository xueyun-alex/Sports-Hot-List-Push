# 体育热榜 24 小时监控

监控 [今日热榜](https://tophub.today/) 体育板块下 4 个榜单，每 5 分钟采集一次 Top10，按出现次数生成日报。

## 监控榜单

| 平台 | 榜单 |
|------|------|
| 新浪体育新闻 | 点击量排行 |
| 抖音 | 体育榜 |
| 虎扑社区 | NBA论坛热帖 |
| 懂球帝 | 今日头条 |

## 报告时间

- **18:30**：统计过去 10 小时（08:30 ~ 18:30），输出各平台 Top5 + 全站 Top5
- **08:30**：统计过去 14 小时（昨日 18:30 ~ 08:30），输出各平台 Top5 + 全站 Top5

报告追加写入 `data/hotlist_report.txt`。若已配置 PushPlus，同一时间会将**本次刚生成的报告**推送到微信。

## 手机推送（微信 ClawBot）

通过 [PushPlus](https://www.pushplus.plus) 的 **微信 ClawBot** 渠道，将报告推送到微信。

1. 在 [pushplus.plus](https://www.pushplus.plus) 注册并完成**实名认证**（未实名时接口返回 905，无法发送）。
2. **个人中心 → 渠道配置 → 微信 ClawBot → 立即绑定**（扫码绑定）。
3. 绑定后向 ClawBot **主动发一条消息**，点击「我已发送」，监听状态变为「已激活」。
4. 复制用户 Token，在项目目录或 exe 同目录创建 `.env`（参考 [`.env.example`](.env.example)），或设置环境变量：

```powershell
$env:PUSHPLUS_TOKEN="你的Token"
$env:PUSHPLUS_SECRET_KEY="你的SecretKey"
$env:PUSHPLUS_CHANNEL="clawbot"
```

**SecretKey** 用于查询消息投递状态（个人中心 → 开放接口 → 用户密钥）。配置后，08:30 / 18:30 定时推送会轮询 PushPlus 确认微信已收到；若未送达则自动重发（默认最多 3 次）。

可选环境变量：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PUSHPLUS_VERIFY_ENABLED` | 有 SecretKey 时为 true | 设为 `0` 可关闭投递验证，仅重试 API 提交失败 |
| `PUSHPLUS_PUSH_MAX_RETRIES` | `3` | 单次报告最多发送次数 |
| `PUSHPLUS_VERIFY_POLL_INTERVAL` | `5` | 轮询间隔（秒） |
| `PUSHPLUS_VERIFY_TIMEOUT` | `90` | 单次发送后轮询最长等待（秒） |
| `PUSHPLUS_RETRY_DELAY` | `10` | 重发前等待（秒） |

投递状态 `status=2` 表示 PushPlus 已成功投递到 ClawBot/微信，不代表用户已阅读消息。若账号启用了开放接口 IP 白名单，需将运行机器 IP 加入白名单。

程序启动时会自动读取同目录下的 `.env`（已存在的环境变量不会被覆盖）。

5. 保持 `python main.py` 常驻（或配置 Windows 任务计划程序开机启动）。
6. 每天 **08:30**、**18:30** 自动生成报告并推送当次报告正文到微信。

**ClawBot 使用限制**（[官方说明](https://pushplus.plus/doc/channel/clawbot.html)）：

- **首次使用前**：扫码绑定后，需先在微信里**主动给 ClawBot 发一条消息**，PushPlus 才能下发推送（推送测试同理）
- 每推送 **10 条**后，需再主动发一条消息给 ClawBot
- 每 **24 小时**内需至少主动对话一次，否则后续推送可能失败

建议每天固定时间给 ClawBot 发一条消息保持激活。本项目每天 2 次推送，24 小时限制是主要注意点。

未设置 `PUSHPLUS_TOKEN` 时仅写入 `data/hotlist_report.txt`，不影响采集与报告生成。

### 推送联调

生成测试报告后，用晚间报告内容试发一条推送：

```bash
python verify.py --push
```

需已设置 `PUSHPLUS_TOKEN`。

## 安装与运行

需要 Python 3.10 或更高版本。

```bash
pip install -r requirements.txt
python main.py
```

启动后会打开**桌面监控窗口**，立即采集一次并在窗口中展示 4 个平台的 Top10 热榜，之后每 5 分钟自动刷新。

### 窗口操作

**实时热榜** 标签页：

- **实时展示**：4 个平台热榜以 2×2 网格排列，显示排名与标题
- **双击条目**：在浏览器中打开对应链接
- **立即刷新**：点击右上角按钮手动触发一次抓取
- **选中条目**：底部状态栏显示完整标题

**历史记录** 标签页：

- **浏览采集数据**：从 `data/records.db` 读取历史记录，表格展示 ID、平台、排名、标题、采集时间
- **筛选**：按平台（全部 / 各平台）与时间范围（今天、最近 24 小时、最近 7 天、全部）筛选后点击「查询」
- **首次进入**：切换到该标签页时自动加载「今天」的全部平台数据
- **双击条目**：在浏览器中打开对应链接（有 URL 时）
- **数据量**：单次最多显示 500 条，底部显示总条数

**热榜计数** 标签页：

- **频次统计**：按标题聚合，展示在选定时间范围内的上榜次数（与 `hotlist_report.txt` 中 `(N次)` 含义相同）
- **筛选**：按平台（全部 / 各平台）与时间范围（今天、最近 24 小时、最近 7 天、全部）筛选后点击「查询」
- **首次进入**：切换到该标签页时自动加载「今天」的全部平台数据
- **表格列**：排名、平台、标题、次数、最后出现时间；底部显示统计窗口、采集轮次与结果条数
- **双击条目**：在浏览器中打开对应链接（有 URL 时）

**通用**：

- **关闭窗口**：停止后台调度并退出程序

## 打包为 exe

将桌面应用打包为 Windows 单文件可执行程序（无需安装 Python）：

```powershell
.\build.ps1
```

产物位于 `dist/SportsHotList.exe`。将 exe 复制到任意目录即可运行，首次启动会自动在同目录创建 `data/`。

**PushPlus 配置**（exe 模式）：在 exe 同目录放置 `.env` 文件，或设置系统环境变量。

**开机自启**（exe 模式）：任务计划程序 → 启动程序 → 选择 `SportsHotList.exe` 完整路径。

也可手动构建：

```powershell
pip install pyinstaller
pyinstaller --noconfirm SportsHotList.spec
```

## Windows 开机自启

1. 打开「任务计划程序」
2. 创建基本任务 → 触发器选「计算机启动时」或「登录时」
3. 操作选「启动程序」：
   - **源码运行**：`python.exe`，参数填 `main.py` 完整路径，起始于项目目录
   - **exe 运行**：选择 `SportsHotList.exe` 完整路径

也可使用 [NSSM](https://nssm.cc/) 将程序注册为 Windows 服务。

## 数据文件

- `data/records.db`：SQLite 采集记录
- `data/hotlist_report.txt`：汇总报告
