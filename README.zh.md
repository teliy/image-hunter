# Image Hunter

[English](README.en.md) | 中文 | [Русский](README.md)

本地图片浏览 **+ 搜索引擎图片搜索 + 按链接批量保存** — 全部集中在一个窗口的四个标签页中（第四个是“📜 日志”：程序运行记录）。支持 Windows 和 Linux。

使用 Python + PySide6 (Qt6) 编写：繁重操作（渲染、网络、图片解码）由原生 Qt 完成，因此界面快速流畅。

> **⚡ 特别优化 — 网络及网络磁盘（SMB/NAS、挂载的共享文件夹）的快速工作**：文件夹一次请求即读完，缩略图仅为列表可见部分生成，已生成的预览缓存到磁盘。即使文件夹中有数千张照片，也不会卡顿 — 程序不卡，网络也不堵。详见[“网络及网络磁盘的快速工作”](#网络及网络磁盘的快速工作)。

## 网络及网络磁盘的快速工作

Image Hunter 从第一天起就是为“照片存放在网络磁盘（NAS、Windows 共享、挂载文件夹）而带宽有限”的场景设计的。普通看图软件在这种场景下会卡死：列出 10000 个文件意味着 10000 次网络 stat 调用，批量加载缩略图更会占满带宽。下面说明具体做了什么以及为什么有效。

**1. 文件夹一次遍历读完 — 不逐文件 stat。** 经典的 `os.listdir()` + 逐文件 `os.stat()` 在 SMB 网络中意味着每个文件两次网络操作。Image Hunter 使用 `os.scandir()`：文件类型、大小和修改时间随目录枚举一起返回 — 无论文件夹中有多少文件，打开它只需一次网络操作。隐藏文件和图片的筛选也基于同一批数据，不产生任何额外请求。

**2. 懒加载缩略图：只加载看得见的部分。** 完全禁用了批量预览加载。缩略图仅为列表可见部分（外加一屏余量）生成；向下滚动时加载新的一批，向上滚动时不会重复读取。打开网络文件夹时，程序只请求屏幕上实际显示的文件（典型窗口中一千张里只取六张）。“🖼 缩略图”开关可完全关闭预览 — 状态会在多次运行之间保留。

**3. 磁盘缩略图缓存 — 再次打开瞬间完成。** 每张生成好的缩略图写入 `%LOCALAPPDATA%\ImageHunter\thumbs`（Linux：`~/.cache/ImageHunter/thumbs`）。键为“路径 + 大小 + mtime”的 SHA-1：文件一变化，对应缓存自动失效。再次打开同一个网络文件夹时直接从本地缓存渲染，为获取图片不会发起任何网络请求。缓存上限 256 MB，写入是原子性的（通过临时文件）— 网络中断也不会留下损坏的缩略图。

**4. 任务世代：离开文件夹 — 过期任务静默丢弃。** 每次扫描都分配世代编号。迟到的旧文件夹缩略图和搜索结果会被丢弃：任务队列不会堆积，网络不会传输已无用的数据。

**5. 子文件夹搜索 — 后台运行，不阻塞窗口。** 按文件名搜索在后台线程中以同样的“一次遍历” scandir 进行，边扫描边返回结果：窗口保持响应，网络负载均匀，搜索期间不读取缩略图。

**6. 界面 — 设置一次即可。** 文件夹树和缩略图条的宽度在多次运行之间保留；图标分批交给列表 — 数百个新行不会引发重绘风暴。

**7. 下载中的网络 — 快速而有分寸。** 下载通过 QThreadPool 最多并行 6 个文件，以 64 KB 块流式写入磁盘（文件不会整个占用内存），超时 10/60 秒，单文件上限 100 MB。保存使用 3 个线程 — 对来源网站更友好。

**8. 更新绕过 CDN 缓存。** 安装程序和更新检查通过 `codeload.github.com` 获取代码，该服务实时生成压缩包：推送后新版本立即可用，不受 `raw.githubusercontent.com` 5 分钟缓存的影响。

## 功能

**📁 我的图片** — 本地看图：
- **左侧磁盘和文件夹树**：挂载的磁盘和设备（悬停提示显示剩余空间）、“主目录”和“图片”快捷链接；文件夹懒展开，点击文件夹立即显示其中图片；面板宽度可用鼠标调整；“⟳”按钮刷新磁盘列表（插入 U 盘后使用）；
- **文件夹筛选**：树上方的“🔍 筛选文件夹…”框 — 输入时树中只保留名称包含这些字母的文件夹：其余隐藏，
  到匹配项的分支自动展开，树上方的计数器显示找到的文件夹数量；筛选即时完成，不会重新扫描磁盘 —
  树只在预算内加载更多层级（每次 300 个文件夹或 1.5 秒），再大或网络的磁盘也不会卡住窗口；
  不区分大小写，单击打开文件夹，回车打开第一个结果，Esc 重置；不显示隐藏文件夹；
- **懒加载缩略图**（见上文网络部分）及“🖼 缩略图”开关；
- **多选与拖放**：在缩略图条中选中图片（Ctrl/Shift，与资源管理器相同）后拖到资源管理器、邮件或任何其他应用 — 传递的是原始文件（`text/uri-list`）；拖放启动有三条独立保障（事件过滤器、自实现的鼠标移动跟踪、Qt 内置机制），每一步都会写入日志；**如果无法拖动 — 无拖放备用方案：** `Ctrl+C`（或右键 →“复制所选文件”），然后在需要的地方粘贴 — 资源管理器或浏览器中 `Ctrl+V`；
- **按文件名搜索**：输入文件名的一部分 — 找到当前文件夹及所有子文件夹中的图片；无需通配符，不区分大小写，结果随扫描逐步出现；**“忽略连字符”** 复选框在匹配时不区分连字符 — 查询“23542-23523”同样能找到“2354223523”（零件编号的写法不一致：连字符位置不同或没有）；复选框状态会被记住；
- **删除文件**：按 `Delete` 或右键 →“🗑 删除” — 所选图片移入回收站（可从资源管理器还原）；确认对话框显示文件数量，每次失败都会连同原因写入日志。在没有回收站的磁盘上（网络磁盘、部分移动设备），程序会在单独确认后提供永久删除；
- 启动时自动打开上次的文件夹（不超过 2000 张图片时），并恢复关闭前的最后一个搜索请求；
- 全屏查看，缩放（`+` / `−` / `Ctrl+滚轮`）、“适应窗口”、“100%”；
- ←/→ 导航，自然排序（file2 < file10）；
- **支持 AVIF**：`.avif` 文件在缩略图条中显示并支持全屏查看，链接下载的 AVIF 图片（电商平台即使以 `.jpg` 名义也返回 AVIF）可重新保存为任一格式；解码器为 Pillow + pillow-avif-plugin（自动安装）；
- 选中的图片在后台线程加载 — 在网络磁盘上选择文件（或读取大型 AVIF）不再卡住窗口（“未响应”）；
- 动图 GIF，支持 JPG/PNG/WEBP/BMP/GIF/AVIF；
- 双击缩略图 — 用系统看图程序打开；“在文件管理器中显示”按钮；
- 缩略图条可通过分隔条用鼠标拉伸（面板宽度在多次运行之间保留），搜索框位于工具栏。

**🌐 图片搜索** — 内置 Chromium 浏览器：
- **浏览器式多标签页**：“＋”/Ctrl+T 新建搜索标签页，每个标签页有独立的搜索引擎和浏览器；右键标签页可复制 / 关闭 / 关闭其他 / 关闭右侧；× 关闭标签页（关闭最后一个会新建空白页），标签页可拖动排序；标签页标题为所选搜索引擎，圆点为品牌色（Yandex — 红色，DuckDuckGo — 橙色，Google — 蓝色，Bing — 绿色）；打开的标签页在下次启动时恢复；
- **一个输入框，全部搜索引擎**：标签页上方有共享搜索框；回车或点击**“🔎 全局搜索”**，
  关键词立即在全部 11 个搜索引擎中打开 — 每个引擎一个标签页（已打开的标签页会重新加载结果）；
- 搜索引擎（11 个）：Yandex 图片、Google、Bing、DuckDuckGo（安全模式）、
  Brave、Startpage、Mojeek、Baidu、Sogou、Naver、Mail.ru；
- Yandex 验证码可直接在内置浏览器中输入；
- **结果卡片上的复选框**：用橙色勾选标记需要的图片 — 按钮上出现计数，“下载已选”将下载大尺寸原图（Yandex 取 `origUrl` — 与点击预览打开的是同一个文件，例如 `avatars.mds.yandex.net/get-mpic/…/orig`；其他搜索引擎取卡片链接参数中的原图）；
- 复选框支持最新版 DuckDuckGo 页面结构（2025）：卡片不再使用熟悉的类名，“原图”来自没有文件扩展名的 Bing 缓存链接 — 现在也能识别并勾选；
- 复选框同样支持最新版 Google 图片结果页（udm=2）：识别无扩展名的 `encrypted-tbn0.gstatic.com`/`googleusercontent` 缩略图，稍后加载图片的懒加载卡片也会出现勾选，页面的持续重绘不再延迟复选框的出现；
- 复选框同样支持最新版 Brave（无扩展名的 `imgs.search.brave.com` 代理缩略图 — 从 URL 路径中的 base64 解出真实原图）、Sogou（卡片类名与 `drag-img` 属性）和 Mail.ru（结果位于嵌套框架中 — 复选框和链接收集同样支持框架内页面）；
- 无限滚动加载的卡片也会被复选框覆盖；
- **“✕ 取消选择”** — 一键取消所有橙色勾选（有勾选时才可用）；
- **“💾 保存到文件夹”** — 勾选的卡片转换为所选格式（WebP、PNG、JPEG、BMP、TIFF — 选择器在按钮旁且会被记住），保存到“我的图片”标签页当前打开的文件夹：第一个文件为 `名称.ext`，之后为 `名称-1.ext`、`名称-2.ext`… **绝不覆盖已有文件：** 跳过被占用的名称，且写入前会再次检查 — 如果 `name.webp` 和 `name-2.webp` 已存在，新文件将变为 `name-1.webp` 和 `name-3.webp`。JPEG/BMP 的透明部分铺白底，尊重 EXIF 旋转。保存时会询问名称（默认为搜索关键词）；若未打开文件夹，会提示选择；保存的文件立即出现在看图中。
- **“📋 收集链接”** — 与之前相同：将打开的结果页上的所有图片（缩略图、DuckDuckGo 代理中的原图、Yandex `data-bem`/`data-state` JSON 中的原图）整批送到下载。

**⬇️ 下载** — 保存管理器：
- 按直链批量下载（最多 6 个文件并行）；
- 手动粘贴链接（每行一个）；
- 会话内链接去重，不覆盖已有文件（`-1`、`-2`… 后缀）；
- 文件名取自 URL，扩展名按 `Content-Type` 修正；
- 当 CDN 拒绝访问（401/403/429）时，下载器会尝试备用方案：不带 Referer、带图片站点自身的 Referer，对 Cloudflare `/cdn-cgi/image/…` 包装链接则尝试直连原始图片地址；
- 下载文件夹可选（默认 `Pictures\ImageHunter`），单文件上限 100 MB。

**📜 日志** — 运行记录（标签页添加在最右侧）：
- 打开了哪些文件夹、搜索找到了什么、哪些文件被拖动及拖放如何结束、下载/保存了多少、发生了哪些错误；如果某个文件下载或保存失败，日志中会同时显示链接和原因（例如“不是图片 (text/html)”、超时、“文件过大”）；
- 错误标红、警告标橙；日志保留最近 5000 行；
- “🧹 清空”与“📋 复制全部”按钮 — 便于将日志附在错误报告中；未捕获的异常同样进入日志；
- 主窗口标签页可用鼠标拖动并任意重排。

应用图标（“带放大镜的照片”）由程序绘制并嵌入窗口；随附 Windows 多尺寸 `app_icon.ico`。

## 界面语言

俄语、英语和中文（简体）。切换器位于状态栏；翻译即时生效，无需重启，选择会被记住。

## 安装

### 一行命令安装（推荐）

安装程序会询问安装文件夹，创建虚拟环境，下载依赖并创建快捷方式。

**Windows**（PowerShell — 整行复制）：

```powershell
irm https://codeload.github.com/teliy/image-hunter/zip/refs/heads/main -OutFile "$env:TEMP\ih.zip"; Expand-Archive "$env:TEMP\ih.zip" "$env:TEMP\ih-src" -Force; powershell -NoProfile -ExecutionPolicy Bypass -File "$env:TEMP\ih-src\image-hunter-main\install.ps1"
```

**Linux**（bash）：

```bash
curl -fsSL https://raw.githubusercontent.com/teliy/image-hunter/main/install.sh | bash
```

安装程序检查 Python 3.10–3.14（缺失时提议安装），询问安装位置，下载代码（无需 git），创建 `.venv`，安装依赖，并创建开始菜单快捷方式（Windows）或 `.desktop` 条目与 `image-hunter` 命令（Linux）。

> **Alpine Linux (musl)：** 安装程序支持 `apk` 并接受 Python 3.10–3.14（stable 为 3.12，edge 为 3.14）。PySide6 没有 musl 轮子，因此安装程序会安装 `gcompat` 并允许 pip 选用 glibc 轮子——通常足够，但 QtWebEngine 在 musl 上仍可能无法启动；更稳妥的方案是使用 Docker 或基于 glibc 的发行版（Debian、Ubuntu、Fedora）。

**更新与卸载：**

| 操作 | Windows | Linux |
|---|---|---|
| 更新 | `ImageHunter.bat update`，或直接在程序内：“帮助 → 检查更新” / “🔄 更新”按钮 (Ctrl+U) | `image-hunter update` |
| 卸载 | `ImageHunter.bat uninstall` | `image-hunter uninstall` |
| 版本 | `ImageHunter.bat version` | `image-hunter --version` |

### 从私有仓库安装（使用令牌）

对于**私有**仓库，GitHub 不会在未授权的情况下通过 `raw.githubusercontent.com` 提供文件 — 常规单行命令会返回 `404: Not Found`。需携带 `Authorization` 头下载安装程序并在本地运行。

**Windows**（PowerShell，一行 — 替换为你的令牌）：

```powershell
$t="ghp_YOUR_TOKEN"; iwr https://raw.githubusercontent.com/teliy/image-hunter/main/install.ps1 -Headers @{Authorization="token $t"} -UseBasicParsing -OutFile "$env:TEMP\ih-install.ps1"; $env:IH_GH_TOKEN=$t; powershell -NoProfile -ExecutionPolicy Bypass -File "$env:TEMP\ih-install.ps1"
```

**Linux**（bash）：

```bash
export IH_GH_TOKEN=ghp_YOUR_TOKEN
curl -fsSL -H "Authorization: token $IH_GH_TOKEN" https://raw.githubusercontent.com/teliy/image-hunter/main/install.sh | bash
```

令牌需要仓库读取权限：classic — `repo` scope；fine-grained — “Contents: Read-only”。安装程序将令牌保存在安装文件夹内的 `.gh_token` 中以便日后自动更新；不需要时请删除该文件。
非交互运行变量：`IH_ASSUME_YES=1`、`IH_DIR=<路径>`、`IH_PYTHON=/path/to/python`（自动探测不合意时手动指定解释器）。

### 手动安装

需要 Windows 10/11 和 Python 3.10–3.14（64 位）。

```bat
git clone https://github.com/teliy/image-hunter.git
cd image-hunter
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## 使用方法

1. **找图片：**“图片搜索”标签页 → 输入关键词 → 选择搜索引擎 → “搜索”。
   或在标签页上方的共享搜索框中输入 — “🔎 全局搜索”会立即在所有搜索引擎中打开该关键词。
2. **收集链接：**等待结果页加载（可向下滚动）→ “📋 收集链接”。列表自动进入“下载”标签页，下载立即开始。
3. **手动保存：**“下载”标签页 → 粘贴直链 → “⬇ 下载链接”。
4. **查看结果：**“打开”按钮打开下载文件夹；同一文件夹也可在“我的图片”标签页中打开。

## 项目结构

```
image-hunter/
├── install.sh                 # Linux 安装程序 (curl | bash)
├── install.ps1                # Windows 安装程序 (irm | iex)
├── main.py                    # 入口
├── requirements.txt
└── app/
    ├── __init__.py
    ├── core/
    │   ├── extractor.py       # 从结果页 JS 收集链接
    │   ├── downloader.py      # 多线程下载器
    │   ├── updates.py         # 检查更新、在程序内启动安装程序
    │   ├── image_saver.py     # 转换为 WebP/PNG/JPEG/BMP/TIFF，不覆盖已有文件
    │   └── i18n.py            # 轻量 i18n：ru/en/zh 字符串，即时重翻译
    └── ui/
        ├── main_window.py     # 主窗口、标签页
        ├── local_viewer.py    # 本地图片查看器
        ├── web_search.py      # 内置搜索引擎浏览器
        └── downloads.py       # 下载表格
```

## 链接收集的原理

JS 脚本（`app/core/extractor.py`）在结果页上运行，收集 `img[src]`、`srcset`、懒加载 data 属性；从 `external-content.duckduckgo.com/iu/?u=…` 代理中还原原图；解析 Yandex `data-bem` 属性中的 JSON；扫描原始 HTML（还原 `\u002F` 和 `\/`）寻找文件直链。每次最多收集 500 个链接。页面并未被“破解” — 只利用浏览器已经下载并显示的内容。

## 说明

- 滚动过快时 Yandex 图片会弹出验证码 — 直接在内置浏览器中输入即可。
- 请尊重版权：仅下载个人使用的图片，或经权利人许可。
- 可能的改进（roadmap）：滚动时自动收集链接、按图片大小过滤（HEAD 请求）、可暂停队列、导出链接列表、通过 PyInstaller 打包 .exe。

## 故障排除

**程序在 Linux 上卡死（Wayland 会话）。** 当 wayland 插件加载失败时（启动时终端
显示 `Could not load the Qt platform plugin "wayland"`），应用程序会通过 XWayland
运行，此时内置浏览器与显卡驱动的组合可能会导致整个窗口彻底卡死。从 v0.6.4 起
Image Hunter 会在启动时自动检测这种情况并禁用内置浏览器的 GPU —— 页面改用软件
渲染（不影响搜索和下载速度），并在“日志”中写入说明。手动控制：

- `IH_GPU=0 image-hunter` —— 强制禁用 GPU；
- `IH_GPU=1 image-hunter` —— 保持 GPU 启用，忽略自动检测；
- `QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu" image-hunter` —— 通过 Chromium 标准
  标志达到同样效果（多个标志用空格分隔）。

如果搜索标签页始终空白（Alpine/musl 以及 Chromium 沙箱无法启动的其他系统），
请添加 `--no-sandbox`：

    QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu" image-hunter

**搜索标签页灰色，终端出现 render process 相关信息** —— 程序现在会自动重启崩溃
的标签页渲染进程（最多两次），事件会显示在“日志”中。

## 许可证

MIT — 见 [LICENSE](LICENSE)。
