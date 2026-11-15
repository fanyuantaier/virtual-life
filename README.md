# Virtual Life · 虚拟人生成器

<p align="center">
  <a href="#中文"><img src="https://img.shields.io/badge/文档-中文-blue" alt="中文"></a>
  <a href="#english"><img src="https://img.shields.io/badge/docs-English-blue" alt="English"></a>
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT">
  <img src="https://img.shields.io/badge/python-3.10+-blue" alt="python">
  <img src="https://img.shields.io/badge/LLM-OpenAI%20compatible-orange" alt="LLM">
  <a href="#演示"><img src="https://img.shields.io/badge/演示-真实输出-ff69b4" alt="demo"></a>
</p>

**一个数字人格引擎：AI 从出生开始活一遍——没有人设，只有一张随机的家庭环境卡，人格由经历的不可预测事件逐渐沉淀。**

她按真实时钟过活：凌晨做梦（素材由遗忘曲线决定），黄昏情绪泛起，下雨天心情对应真实的天气。她记忆遵循艾宾浩斯分级衰减——琐事一周就淡忘，大事终身留痕。她有一个自己看不见的世界：NPC 们在暗线里过日子，消息经传闻失真后才传到她耳朵。

她不记得一切，也不假装记得。她会说「记得不太清了，大概……」——因为人就是这样。

<a name="中文"></a>
## 演示（真实输出，未编辑）

**冬至夜，三地饭**（感动度 62）：

> 十点半，姆妈的电话比周日早了打来，我握着手机听她讲期末卷子堆成山，嗓子还是哑的，就先问了一句还哑勿哑。她问寒假哪天回苏州住齐，我把日子含糊过去了，转头把台灯拧亮，四级词汇摊开——红笔帽滚在桌角，跟小时候那张批过的卷子一个样。老周办公室的灯亮到很晚，我这盏也亮着，谁也没比谁早走。

**一个梦**（记忆碎片自动重组，醒来即忘）：

> 梦里是冬至，教室里外婆搬来冬酿酒坛子，桂花浮勒酒面上头。台面上留牢一个空位，我拨伊斟仔一小杯：「开车格人夜里勿吃酒——箇杯挂账。」啥人开车？我急得想勿起来，只晓得箇杯酒一直挂勒账上，呒没人来还。……木秤又挂上了箩筐，外婆叫我坐进去称人。想问伊箇杯酒几时来还——闹钟响了。

**18 岁年度反思**（系统自动蒸馏）：

> 我发现自己的爱是长成章程和账本样子的：反扣碗、瓜账、月信、礼拜三的药、立夏的秤——说不出口的想念和担心，都被我翻译成一格一格能核对的条目。

更多真实输出见 [docs/showcase.md](docs/showcase.md)。架构图见 [docs/architecture.md](docs/architecture.md)。

## 为什么不是又一个聊天机器人

| 聊天机器人 | 本项目 |
|---|---|
| 记忆 = 聊天记录，塞满就截断 | 记忆 = 完整人生（4700+ 节点），艾宾浩斯分级衰减 |
| 无时间感，你打开才存在 | 按真实时钟过活：凌晨做梦、黄昏泛起、下雨天对应真实天气 |
| 人格 = 一段 system prompt | 人格从事件里涌现：L1 事实 → L2 场景 → L3 画像，每条可追溯 |
| 对话者第一天就过度热情 | 网友距离感：家庭故事一句话挡回，40 轮才到"熟" |
| 记住一切 = 隐私噩梦 | 遗忘曲线 + 检索时模糊化 + 一键导出/真删除 |

**三个独有机制**（开源 AI 伴侣项目里找不到，组合可发表）：

1. **遗忘曲线作为记忆属性** —— 每条记忆有关键级（key0-3）和独立衰减常数。琐事一周剩 31%，大事终身留痕（key3 下限 0.30）。模糊化发生在检索时：库里原文不动，"她想起来什么"会失真——就像人。
2. **梦境 = 遗忘曲线的副产品** —— 没有为做梦写专门逻辑：梦的素材就是"高关键记忆 + 快淡忘的记忆"，遗忘曲线顺带决定了什么入梦。凌晨自动生成，醒来即忘。
3. **信息不对称** —— 世界编年史分公开/暗线双轨；传闻逐手失真（1 手原样 → 4 手只剩轮廓）才传到她耳朵。她活在信息迷雾里，就像人。

## 演示：沈青蔓

`profiles/nanan/` 是用本引擎养出的第一个完整人格——seed=42，苏州，父母离异随母亲，父亲是长途车司机，外婆同住。0 → 18 岁 552+ 关键事件、4709 记忆节点、5 篇梦境日记。

她的名字有完整的叙事弧（0.1 岁上户口红笔写名 → 6.5 岁瓜苗边学写 → 17.4 岁高考报名 → 18.2 岁毕业证铅印）。她 18 岁的年度反思里，系统自动归纳出：

> 我发现自己的爱是长成章程和账本样子的：反扣碗、瓜账、月信、礼拜三的药、立夏的秤——说不出口的想念和担心，都被我翻译成一格一格能核对的条目。

这条没有一条是设定出来的——它从 1 岁的糖芋艿、13 岁的瓜账、18 岁的药盒对账里自己长出来。

## 快速开始

```bash
pip install -r requirements.txt    # 只有 pydantic + openai
python start.py                    # 首次引导配置模型端点（Ollama/llama.cpp/云API）
```

之后按菜单：

```bash
python start.py new --seed 42     # 创建新人生（随机出生 → 快进到 18 岁）
python start.py chat              # 和她聊天
python start.py live              # 常驻：按真实时钟过日常 + 凌晨自动做梦
python start.py stats             # 查看状态
```

网页版（聊天 + 人生时间轴 + 她的朋友圈 + 上帝之手干预）：

```bash
python web/server.py              # http://127.0.0.1:5100
```

## 导入你的真实记忆

```python
from engine.person import Person
from engine.importer import import_wechat_txt, import_diary_txt, import_photo_dir

p = Person.load("nana")
import_wechat_txt(p, "微信聊天记录.txt", peer_name="妈妈")   # 逐条入 chat 记忆
import_diary_txt(p, "我的日记.txt")                          # 按日期分段入事件
import_photo_dir(p, "照片目录/")                             # 按时间生成时刻记忆
```

导入的记忆默认 key=2（重要但非终身锚点），可在记忆库中手工调级。

## 架构

```
start.py                 一键入口
engine/
  person.py              Person：记忆/需求/导出（与具体人格解耦）
  importer.py            数据导入：微信/日记/照片
  profiles.py            多实例：profiles/<name>/ = 一个独立人格
world/
  director.py            导演：LLM 生成事件（3候选择异/禁用清单/泄密检测）
  world_sim.py           世界自转：NPC 目标/季节事件/编年史（公开+暗线）
  needs.py               需求衰减：四项需求 × 性格修正 → 状态逼出事件
  rumor.py               传闻传播：逐手失真
  physics.py             物理层：骨架/校验（时间/钱/地点/情绪连续性）
  fallback.py            兜底日：LLM 全挂时世界照常转
memory/
  store.py               SQLite 记忆库（向量+BM25+RRF 混合检索）
  forgetting.py          遗忘曲线：key0-3 分级衰减 + 检索时模糊化
  distill.py             分层蒸馏：L1→L2→L3
  dream.py               梦境生成
  persona.py             人格文件（自动归档防膨胀）
web/                     聊天 + 时间轴 + 朋友圈 + 上帝之手
harness/                 训练编排：三档消耗力度（normal/burst/max）
```

## 架构图

![architecture](docs/architecture.md) 中的 mermaid 图在 GitHub 上原生渲染：

```mermaid
graph TB
    subgraph 现实层
        CLOCK[真实时钟] → TICK[调度器]
        WX[天气] → TICK
        NEWS[新闻 RSS] → TICK
        USER[用户消息/干预] → TICK
    end
    TICK → DIRECTOR[导演 LLM]
    FORE[伏笔表] → DIRECTOR
    DIRECTOR → PLAN[DayPlan] → PHYS[物理层校验] → REACT[主角 LLM]
    MEMRET[记忆检索<br/>向量+BM25+RRF] → REACT
    PERSONA[L3 人格画像] → REACT
    REACT → DIARY[日记] → STORE[(遗忘曲线记忆库)]
    STORE → MEMRET
    STORE → DISTILL[L1→L2→L3 蒸馏] → PERSONA
    SLEEP[凌晨] → DREAM[梦境] → STORE
    USER -.->|上帝之手| PLAN
```

## 设计文档

- **不可预测性的实现**：事件不由概率抽取。只有三种诞生方式——伏笔成熟（主来源，从"未兑现伏笔表"判断戏剧时机）、开放生成、现实注入（真实天气/新闻/你的消息）。没有骰子。
- **防同质化四件套**：禁用清单自增长、向量+字符双路查重打回、3 候选择异、因果优先于新颖。
- **级联**：主角今天的决策写回状态 → 改变明天导演的输入 → 明天依赖今天。对明天的预测必须等到明天——这是工程上对"完全不可预测"的定义。
- **上帝之手**：用户干预写队列，导演必须消化进当天计划——"我能干预，但干预带来我没预料到的后果"。
- **性能**：记忆检索走 SQL 候选集（热窗 90 天 + 关键记忆永久 + 冷抽样），4700 条实测 43ms，无需向量数据库。

## 模型要求

任何 OpenAI 兼容端点。实测：
- GLM-5.3-Flash 级：中文细腻度最好（苏州话质感），需给足 reasoning+长输出预算
- DeepSeek-V4 级：6 秒出合法 JSON，速度快
- Qwen3-8B 级：可用
- 4B 级：勉强（代码内有多层输出容错防御，但怪癖多）

Embedding 推荐 `nomic-embed-text`（无 embedding 端点时自动降级为字符 n-gram，功能完整）。

## 已知限制

- LLM 采样不可复现：同 seed 重建的只有出生参数和记忆框架，事件细节每次不同
- 模拟时间线锚定"今天"向未来推进；年度反思的记忆过滤未完全对齐模拟时间
- 长跑期间机器休眠会冻结进程；唤醒后重启即可从断点续跑

## License

MIT
