# 出题老师 · 数学 Agent / Skill

一个以**用户提供的人教版初高中数学教材**为依据、可持续扩充资料库的出题老师。它通过教材目录定位知识范围，通过已核对的正文、例题与习题理解题型；接受知识点、错题或参考试卷，生成原创练习、巩固题或试卷，并核查答案。

> 这个仓库是可公开分享的**程序与流程版本**，不含教材、试卷原件和由它们整理出的题目记录。克隆后资料库为空；请先加入自己有权使用的资料。原项目的入库进度不会随此仓库自动同步。

## 能做什么

| 功能 | 输入 | 输出 |
| --- | --- | --- |
| 知识点出题 | 知识点、教材/册次、题量、难度 | 按已核对教材范围生成原创题，附答案与解析；可先只展示题目 |
| 错题巩固 | 题干、照片/截图/PDF、学生作答 | 识别题型与核心方法，分析有证据的错因，生成同方法变式题 |
| 组卷 | 年级、章节范围，或参考试卷 | 先形成题型与分值蓝图，再生成原创学生卷及独立答案 |
| 资料入库 | 教材或试卷 PDF、Word、图片 | 保存来源、去重、建立索引、逐题核对并记录处理进度 |

题量支持任意正整数，常用选择是 1、5、10、20 道；难度为简单、中等、较难、拓展。出题与组卷后应独立验算。错题没有学生解题过程时，错因只能作为假设。资料入库分为“原件已保存、目录已核对、习题已整理、答案已复核”等阶段，不把上传成功当作全书整理完成。

## 项目结构

```text
AGENTS.md                         项目级行为说明
math-question-teacher/SKILL.md    出题老师的核心流程
math-question-teacher/references/ 各功能的详细规则
math-question-teacher/scripts/    资料登记、检验和报告工具
math-question-teacher/config.json 资料库相对路径配置
agent/teacher.py                  命令行 Agent 入口
webapp/                           仅在本机运行的网页界面
library-template/                 空资料库模板
init_library.py                   初始化个人资料库
library/                          运行后生成；被 Git 忽略
```

Skill 是规则与工作流程；`agent/teacher.py` 是调用 Codex CLI 的本机入口；`webapp/` 是这个入口的本机界面。**网页目前不是公网服务**。若只使用 Skill 规则，可以在支持读取本地文件和图片的 AI 工具中参考它，但命令行入口和网页目前依赖 Codex CLI。

## 快速开始

需要 Python 3；使用 Agent 命令或本机网页时，还需要安装、登录并能在终端运行 `codex` 命令。查看资料库状态及初始化资料库不需要调用模型。

1. 下载或克隆仓库，在项目根目录运行 `python init_library.py`。
2. 运行 `python agent/teacher.py status`，应看到来源数和题目数均为 0。
3. 将自己的教材或试卷按下文方式入库；在教材相关内容核对前，系统不会宣称练习符合某一版教材。

在 Codex 桌面版中打开此文件夹，直接说“把这份教材入库”“按集合的交集出 5 道中等题”或“根据这张错题照片再出一道同方法的题”。根目录的 `AGENTS.md` 会引导 Agent 读取 Skill 与资料库。

### 命令行示例

```powershell
python agent/teacher.py ingest "D:\资料\数学教材.pdf" --kind 教材 --edition "人教A版高中数学必修第一册"
python agent/teacher.py quiz "集合的交集" --count 5 --level 中等
python agent/teacher.py mistake --image "D:\资料\错题.jpg" --work "我算成了并集"
python agent/teacher.py paper --grade 高一 --scope "必修第一册第1章" --question-count 10 --total-score 100
python agent/teacher.py paper --grade 高一 --reference "D:\资料\参考卷.pdf" --total-score 100
python agent/teacher.py status
```

这些路径是示例，需替换为本机文件。也可以运行 `python agent/teacher.py chat` 进行连续对话。各命令可加 `--preview` 查看将执行的命令，先不调用模型。参数详情见 `python agent/teacher.py --help`。

### 本机网页

```powershell
python webapp/server.py
```

启动后在本机打开 `http://127.0.0.1:8765/`。网页提供出题、错题巩固、组卷、资料入库和进度概况；它只监听本机地址。使用说明见 [`webapp/README.md`](webapp/README.md)。

## 资料如何增长

`python init_library.py` 会从 `library-template/` 建立独立的 `library/`。新资料进入 `library/sources/`，来源登记保存在 `library/data/source-register.json`，目录、章节笔记、试卷索引和逐题记录保存在 `library/data/` 下。新增教材建立自己的来源 ID 和目录文件，不覆盖旧版本。入库程序按文件校验值查重；扫描件、公式、图形及答案需要回看原页核对。

`library/` 已被 `.gitignore` 排除，避免把上传的教材、试卷、学生错题和衍生题库误推送到公开仓库。公开分享前仍应查看 Git 提交列表。需要在多台设备之间同步个人资料库时，应自行选择有权限控制的存储方式，并确认相关资料可以共享。

## 当前边界

- 新克隆的仓库**没有内置教材与题库**。知识点出题以实际已入库、已核对的范围为准；范围不足时会说明缺口。
- 图片识别、数学理解与新题生成依赖所接入 AI 的能力；代码本身并未训练出一个独立数学模型。
- 本机网页调用本机 Agent，不是可供别人远程登录的在线服务。仅把网页文件放到 GitHub Pages，不能让它执行 Python 后端或调用本机资料库。
- 参考卷用于分析试卷结构；除非明确要求入库，否则不自动写入通用资料库。

## 贡献与发布

本仓库没有包含第三方教材或试卷，也没有默认授予代码再分发许可。发布前可按自己的授权需求补充 `LICENSE`。提交修改时，请保持 Skill 规则与个人资料库分离，并在 README 中准确描述已经实现和仍需核对的部分。
