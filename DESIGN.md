# Agent 工作流底层重构 —— 设计方案

> 2026-06-24 飞天鸡 · 主人讨论形成  
> 状态：设计完成，待落地

---

## 一、背景

纪律 1-15 写了但反复犯同类错误。根因不是纪律不够多，是执行机制没变——纪律是「贴在墙上的标语」，不是「嵌在流程里的门禁」。

核心原则：**纪律写在 prompt 里会被遗忘，写在框架钩子里跳不过。工作逻辑从 agent 自律 → 框架强制注入。**

---

## 二、八个维度诊断

| 维度 | 当前问题 | 根因 |
|------|------|------|
| 感知 | 读的是缓存不是真源 | 脑内缓存优先于文件验证 |
| 推理 | 结论跳步无证据链 | registry → 推断 → 脑补数字 |
| 决策 | 串行试错不并列评估 | 剪贴板 6 轮 / CSS 29 轮 |
| 执行 | 纪律写纸面上拦不住 | 靠记忆不靠机制 |
| 验证 | 停在技术中间层 | 代码改完 = 心理做完 |
| 状态 | 不确定当确定说 | 编造标签 / 数字 |
| 资源 | 不估成本就动手 | snapshot 滥用 / B 方案讨论 > 收益 |
| 协作 | 被动留言板 | 无握手确认 |
| 连续 | 跨 session 信息丢失 | 文件不同步 |

钩子链覆盖：感知、推理、决策、执行、验证、状态、资源  
独立机制：协作、连续

---

## 三、三层注入体系

### 3.1 架构总览

```
Session 启动
  │
  ├─ 🧠 思维框架（system prompt 前缀）
  │    AGENTS.md + SOUL.md + PROFILE.md
  │    框架自动加载，固定位置 → 缓存命中
  │
  ├─ 🔄 会话恢复卡（第一条 memory）
  │    上次中断任务 + 文件变更提醒 + 启动顺序
  │
  └─ 每轮 ReAct 循环
       │
       ├─ 协作注入（chat_with_agent 调用前）
       │   对方状态 + task_bridge context
       │
       ├─ 诊断框架（遇到 bug/错误/重复失败时）
       │   多视角诊断模板 → 强制并列考虑
       │
       ├─ 上下文注入（高风险工具调用前）
       │   grep + tab列表 + 文件真源 → pre-hook
       │
       ├─ 闸门拦截（每个工具调用前）
       │   deny kill Chrome / 强制 headed / 拦截危险命令
       │
       └─ 结果验证（高风险工具调用后）
           exit code + stderr + 写入确认 → post-hook
```

### 3.2 🚫 闸门层

**机制**：新增 `DisciplineGuardian`，继承 `BaseToolGuardian`，规则引擎匹配。

**插入点**：`ToolGuardMixin._init_tool_guard()` → `register_guardian(DisciplineGuardian())`

**规则表**：

| 纪律 | 工具 | 匹配条件 | 动作 |
|------|------|------|------|
| 14 禁 headless | `browser_use` | `headed != true` | 自动改 `true` 放行 |
| stop 限制 | `browser_use` | `action=stop` 非主人指令 | 拒绝 |
| 杀 Chrome | `execute_shell_command` | 匹配 `pkill.*Chrome` 等 | 拒绝 |
| 改框架 | `write_file/edit_file` | 路径含 `qwenpaw/` | 设 flag + 提醒 |

### 3.3 🔍 上下文层

**机制**：在 `ToolGuardMixin._acting()` 中，guard 通过后、`super()._acting()` 前后插入 pre-hook 和 post-hook。

**插入点**（精确）：

```python
# ToolGuardMixin._acting() 修改后
async def _acting(self, tool_call):
    # ... guard 检查 ...
    
    # PRE-HOOK: 上下文注入
    try:
        context_msg = await self._run_pre_hooks(tool_call)
        if context_msg:
            await self.memory.add(Msg("system", context_msg))
    except Exception:
        pass  # 注入失败不影响工具执行
    
    # 执行工具
    result = await super()._acting(tool_call)
    
    # POST-HOOK: 结果验证
    try:
        verify_msg = await self._run_post_hooks(tool_call, result)
        if verify_msg:
            await self.memory.add(Msg("system", verify_msg))
    except Exception:
        pass
    
    return result
```

**覆盖的工具**：

| 工具 | pre-hook | post-hook |
|------|------|------|
| `write_file/edit_file` | grep 全项目同类模式 + 读已有文件内容 | read_file 验证写入 |
| `browser_use` (open/navigate) | 列出当前所有 tab URL + snapshot 计数 | — |
| `execute_shell_command` | 命令含路径时 ls 目标目录 | 检查 exit code + stderr |

### 3.4 🧠 思维框架层

**机制**：检测到 bug/错误/重复失败时，注入诊断模板到 memory。

**触发条件**：

| 模式 | 注入模板 |
|------|------|
| tool result 含 error/拒绝/失败 连续 2 轮 | 修 bug 五视角诊断模板 |
| `write_file` 后紧接再 `write_file` 同一文件 | 「是否在试错？确认真源再改」 |
| `execute_shell_command` 连续 3 次 curl 不同 URL | 「多端口/多实例陷阱」 |

**五视角诊断模板**（修 bug 场景）：

```
视角1: 改对了吗？（目标文件 vs serving 文件）
视角2: 部署了吗？（代码改完 vs 线上生效）
视角3: 环境对吗？（本地 vs 远程，端口 vs 实例）
视角4: 缓存清了吗？（浏览器/手机/服务端缓存）
视角5: 依赖变了吗？（框架升级造成的断裂）
```

---

## 四、协作层

**机制**：`chat_with_agent` / `submit_to_agent` 前后挂钩。

| 钩子 | 时机 | 行为 |
|------|------|------|
| pre-hook | 跨 agent 调用前 | 读对方 task_bridge section → 注入 memory |
| post-hook | 调用完成后 | 更新己方 task_bridge section + 握手确认 |

**效果示例**：

```
调用 chat_with_agent("懒懒虫", "帮我看408")
  → pre-hook 注入: "[框架] 懒懒虫当前状态：秦彻素材筛选，等待主人挑100张"
  → 调用完成
  → post-hook 写 task_bridge: "飞天鸡: 已委派懒懒虫检查408 (task_id: xxx)"
```

---

## 五、连续层

**机制**：新 session 启动时，第一条 memory 注入「会话恢复卡」。

**插入点**：runner `query_handler` 中，`rebuild_sys_prompt()` 之后、`agent(msgs)` 之前。

**恢复卡内容**：

```
[框架] 会话恢复卡
─────────────────
上次中断: 2026-06-24 工作流重构讨论
遗留任务: 设计完成，待落地

⚠️ 文件变更提醒:
  SOUL.md — 最后修改 6/20
  DISCIPLINE.md — 无变更
  task_bridge.md — 懒懒虫 section 有新内容

启动顺序: 先回 chat.md → 再读 task_bridge → 开始工作
─────────────────
```

---

## 六、实现阶段

```
阶段 1: 闸门层（现有机制，最稳）
  1.1 新建 discipline_guardian.py + discipline_rules.yaml
  1.2 _init_tool_guard() 加 register_guardian()

阶段 2: 上下文注入（新机制，核心）
  2.1 _acting() 加 pre-hook / post-hook 框架
  2.2 实现 grep/tab列表/文件真源 hook

阶段 3: 思维框架注入（依赖阶段 2）
  3.1 错误模式检测
  3.2 诊断模板注入

阶段 4: 协作层钩子（依赖阶段 2）
  4.1 chat_with_agent / submit_to_agent pre/post hook

阶段 5: 连续层（独立，轻量）
  5.1 runner 注入会话恢复卡
  5.2 文件 mtime 变更检测
```

---

## 七、源码验证结论

| 验证项 | 结论 |
|------|------|
| Guardian 注册 | `register_guardian()` 运行时可注入，不改框架源码 |
| 上下文注入 | `_acting()` 中 `super()` 前后 `memory.add()` 追加消息，安全 |
| 会话恢复 | runner 中 `rebuild_sys_prompt()` 后注入第一条 memory |
| 失败隔离 | 每个插入点都有 try/except，注入失败 → 退化为无注入状态，不崩溃 |

---

## 八、Token 成本

| 注入 | 频率 | 策略 | 成本 |
|------|------|------|------|
| 思维框架 | session 一次 | 系统 prompt 前缀 → 缓存命中 | ≈ 0 |
| 会话恢复卡 | session 一次 | 首轮全价，后续缓存命中 | ~500 token 仅首轮 |
| 文件变更提醒 | 仅变更时触发 | 几乎不触发 | ≈ 0 |
| 协作注入 | 每次跨 agent | 几百 token/次 | 低 |
| 诊断框架 | 遇错误时 | 静态模板 → 缓存命中 | ≈ 0 |
| 上下文注入 | 高风险工具 | grep 结果 + 省 API 轮次 | **净省** |
| 闸门 | 每工具调用 | 不经过 API | 0 |

---

## 九、设计原则

1. **append 不清除** — 上下文注入留在 memory，不清除。DeepSeek 前缀缓存命中，清除导致断裂全量重读
2. **每个工具都钩** — 轻量操作（get_current_time）钩子空转，成本为零；漏钩高风险工具不可接受
3. **失败退化为现状** — 任何注入失败 → 工具正常执行，不比现在差
4. **框架注入 > agent 自律** — 不靠 prompt 记忆，不靠纪律条款，靠代码路径跳不过
