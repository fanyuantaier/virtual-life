# 架构图源码（GitHub README 原生渲染 mermaid）

```mermaid
graph TB
    subgraph 现实层
        CLOCK[真实时钟] → TICK[调度器 scheduler]
        WX[天气 wttr.in] → TICK
        NEWS[新闻 RSS] → TICK
        USER[用户消息/干预] → TICK
    end

    subgraph 导演层
        TICK → DIRECTOR[导演 Director]
        FORE[伏笔表] → DIRECTOR
        CHRON[编年史 30天] → DIRECTOR
        BANNED[禁用清单+查重] → DIRECTOR
        DIRECTOR -->|3候选择异| PLAN[DayPlan]
        PLAN → PHYS[物理层校验]
        PHYS -->|不合法打回| DIRECTOR
    end

    subgraph 主角层
        PLAN → REACT[主角 react]
        MEMRET[记忆检索<br/>向量+BM25+RRF] → REACT
        PERSONA[L3 人格画像] → REACT
        REACT → DIARY[第一人称日记]
        REACT → DECISION[决策写回状态]
    end

    subgraph 记忆层
        DIARY → STORE[(SQLite<br/>遗忘曲线 key0-3)]
        DECISION → STORE
        STORE → MEMRET
        STORE → DISTILL[L1事实→L2场景→L3画像]
        DISTILL → PERSONA
    end

    subgraph 夜间
        SLEEP[凌晨 0-6 点] → DREAM[梦境生成<br/>碎片重组 key=1]
        DREAM → STORE
    end

    USER -.->|上帝之手| PLAN
```
