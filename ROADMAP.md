# AutoClip 产品路线图

> AutoClip is currently a **personal-first local tool** for producing upload-ready Shorts from long-form video.
> Commercial SaaS, accounts, hosted credits, cloud processing, and payment are intentionally **deferred**. The near-term goal is better clip selection, retention-oriented scoring, reliable rendering, and a polished local desktop workflow.

---

## 0. 已定的战略前提

| 维度 | 当前决定 | 含义 |
|------|------|------|
| 产品形态 | **Personal-first / local** | 先把 AutoClip 做成自己日常真正会用的工具，不围绕商业化约束架构 |
| LLM 调用 | BYO key / local configuration | API keys remain user-controlled; no hosted LLM proxy is required |
| 视频处理 | **纯本地** | 下载、FFmpeg、Whisper 和最终渲染在本机完成 |
| 数据 | 本地优先 | Projects, transcripts, metadata, exports and performance notes stay local |
| 商业化 | **Deferred** | SaaS、账号、credits、订阅、支付、云端处理全部不进入当前执行计划 |
| 开发方式 | 个人 + AI | 优先复用成熟库/服务，但避免为了未来 SaaS 提前增加后端复杂度 |

## 1. 核心架构判断

- 现在没有任何服务器。**账号、埋点、付费三件事都需要一个云端后端**——这是最大的拐点，规划围绕"用最小代价搭骨架，再渐进长功能"。
- **credits 的精髓 = 计量的 LLM 代理**：唯一上云的是 LLM 调用（经你的代理转发到通义/豆包/OpenAI/Gemini，按 token 记账扣 credits）。**视频处理永远留本地**，你的云成本被钉死在"LLM token + 轻量 API/DB"，可控可预测。
- 由此，免费/付费的天然分界：
  - **免费**：BYO-key（用户自带 key，自己付）或每月少量赠送 credits。
  - **Pro**：credits 套餐 + 高级功能（高准确度模型、批量、无水印、优先等）。

## 2. 技术选型（个人开发者，买 > 造）

| 能力 | 选型 | 理由 |
|------|------|------|
| 云后端 + 鉴权 + DB | **Supabase**（Postgres + Auth + Edge Functions）| 一套搞定账号/数据/函数，solo 最省 |
| LLM 代理 + 计量 | **LiteLLM**（开源代理）放在后端前面 | 统一多家 provider + 自带 token 用量统计，credits 记账的基础 |
| 产品分析 + 埋点 + 灰度 + A/B | **PostHog** | 分析、功能开关、实验一把梭，可云可自托管 |
| 崩溃/错误上报 | **Sentry** | 桌面端 + 后端都接 |
| 支付（国内）| 微信支付 / 支付宝（直连或 Ping++ 等聚合）| Phase 2 |
| 支付（海外）| **Stripe** | Phase 3 |
| 许可/权益 | 自建（订阅状态存 Supabase，桌面端启动校验 + 离线宽限）| 轻量即可 |

## 3. Current Backlog · 短期处理优化

> These items are tracked from real-world Short export validation. Completed items remain visible here so we do not accidentally re-open already-solved work.

### Completed / verified

- [x] **Short clip ending buffer** — vertical Shorts now add a configurable 0.5s post-speech tail by default (`AUTOCLIP_SHORT_END_PADDING_SEC`), capped by source media duration.
- [x] **Short subtitle cleanup** — vertical Shorts no longer pass the original/source SRT into FFmpeg; only AutoClip's generated word-timed ASS karaoke layer is burned.
- [x] **Whisper processor / GPU acceleration audit** — local faster-whisper CUDA inference was verified on the RTX 3050 path; CTranslate2 sees CUDA and the persistent container runtime is wired with the required CUDA user-space libraries.
- [x] **Strict Short quality gate** — incomplete thoughts and invalid/missing Short ranges are rejected before automatic publishing.
- [x] **Title vs. visual hook separation** — long platform titles remain metadata; Shorts render a bounded 3–8-ish word visual hook with two-line wrapping and a short display window.

### Active QA backlog

- [x] **Caption event-boundary hardening** — prevent adjacent ASS karaoke events from rendering together at exact timestamp boundaries. Add regression coverage for zero-overlap phrase transitions and inspect real rendered frames around transitions.
- [x] **Whisper caption text normalization** — investigate occasional visually malformed contraction/word rendering (for example the `there's` transition seen during QA), while preserving the authoritative Whisper word timestamps and spoken wording.
- [x] **Manual export Hook API propagation** — expose `hook_text` through the project export API so manually requested exports use the same short visual hook as automatic Shorts. The renderer already supports it; the API request model is being wired to it.
- [x] **Caption safe-zone / speaker collision pass** — captions now use a lower safe-zone margin and the smart foreground reserves a clean lower band to reduce collisions with source overlays; placement is kept restrained rather than adding aggressive retention effects.
- [x] **Burned-in source subtitle mitigation** — smart vertical exports crop a small configurable bottom band from the foreground (`AUTOCLIP_FOREGROUND_BOTTOM_CROP_RATIO`, default 0.12) because embedded source subtitles cannot be removed by disabling an SRT track. The full frame remains in the blurred background.

### Content-selection backlog

- [x] **Candidate-moment architecture** — evolve Step 3 from “score a segment” toward `find candidates → understand → build complete clip → quality gate → select candidates → hook → render`, while retaining the current pipeline as the compatibility path.
- [x] **Stronger truthful entry-point selection** — score the best *entry point* into a good idea separately from the overall segment score, preferring semantic completeness over arbitrary mid-sentence cold opens.
- [x] **Payoff-aware ending selection** — make the ending decision explicitly optimize for the idea resolving, not merely the interesting segment ending.
- [x] **Mini-story structure signals** — add optional hook/context/development/payoff signals to candidate scoring so the system can distinguish an interesting quote from a self-contained short-form story.

### Virality / Retention Engine backlog

> These are optimization signals, not guarantees of virality. The goal is to improve the system's ability to identify clips with stronger attention, retention, shareability, and rewatch potential, then validate those decisions against real audience performance.

- [x] **Scroll-stop score** — dedicated 1–3 second opening signal for immediate attention, clarity, novelty, emotional force, questions, and bold-but-truthful claims.
- [x] **Curiosity-gap score** — legitimate unanswered-question / information-gap signal with explicit anti-clickbait guidance.
- [x] **Shareability score** — natural reasons to share through relatability, usefulness, identity, emotional resonance, insight, or constructive disagreement.
- [x] **Rewatch / loop score** — replay potential from dense insight, surprising payoff, compact information, opening/ending relationships, or natural looping.
- [x] **Retention-aware candidate ranking** — combines the four retention signals with existing structure scoring while preserving hard publish gates.
- [ ] **Audience-performance feedback loop** — ingest real post-publish metrics such as chose-to-view / viewed-vs-swiped, average view duration, average percentage viewed, completion, likes, comments, shares, saves where available, and replay/retention signals; use them to audit and calibrate AutoClip's prediction scores rather than claiming pre-publish virality.
- [ ] **Performance-based model calibration** — compare predicted candidate scores against real outcomes, identify systematic misses (strong hook but poor retention, high retention but low sharing, etc.), and iteratively adjust scoring weights/prompts using measured data.
- [ ] **Platform-specific retention profiles** — keep the shared content-quality model, but allow platform-specific scoring/packaging profiles for YouTube Shorts, TikTok, and future platforms when their available performance signals or creative constraints materially differ.
- [ ] **A/B export experiments** — once enough real traffic exists, support controlled variants of hooks, caption presentation, opening/ending trims, and packaging so performance differences can be measured instead of guessed.

## 3. 分阶段计划

### Phase A · Retention Engine — 当前执行阶段
**目标**：让 AutoClip 在不增加任何云端产品基础设施的情况下，更稳定地挑出值得发布的 Shorts。

- [x] Candidate-moment architecture
- [x] Truthful entry-point selection
- [x] Payoff-aware ending selection
- [x] Mini-story structure signals
- [x] Scroll-stop score
- [x] Curiosity-gap score
- [x] Shareability score
- [x] Rewatch / loop score
- [x] Retention-aware candidate ranking
- [ ] Real-world validation against exported Shorts
- [ ] Tune scoring weights from observed results
- [ ] Platform-specific profiles only when actual usage justifies them

**出口标准**：AutoClip 输出按结构质量 + 留存优化信号排序的完整 Shorts，同时 hard quality gates 始终优先。

### Phase B · Local product hardening
**目标**：让个人桌面工作流足够稳定，可以长期日常使用。

- Windows real-device validation
- Apple notarization / signing when macOS distribution is needed
- Windows code signing when distributing Windows builds
- Intel / Windows / Linux packaging as needed
- CI build validation
- Tauri updater
- Local crash/error diagnostics
- Privacy-preserving optional local diagnostics
- Home/project-card redesign and preview workflow
- Design system and visual polish

**出口标准**：clean-machine install、可靠更新、稳定的日常工作流，以及完成度足够高的本地产品体验。

### Phase C · Personal workflow expansion
仅在核心 pipeline 稳定后继续：

- Better project search/filtering
- Batch processing
- Export presets and per-platform packaging
- Local performance notes / CSV import for post-publish metrics
- Hook/caption A/B generation as local experiments
- Optional content libraries/templates
- More intelligent source-caption detection

### Deferred · SaaS / accounts / payments
这些内容**暂不属于当前执行计划**。

如果未来 AutoClip 再转向公开商业产品，之前考虑过的 Supabase、LiteLLM proxy、credits、PostHog cloud reporting、payments、subscriptions、Stripe、cloud processing 等可以单独重新规划。当前实现不应为了这些未来可能性增加云端复杂度。

## 4. 横切关注（当前本地产品）

- **Privacy**：API keys、transcripts、source media、metadata 和 exports 默认留在本机，除非用户明确选择外部 provider。
- **Security**：保护本地 secrets，避免 credentials 进入 Git，并把生成媒体/runtime artifacts 排除在版本库之外。
- **Reliability**：优先 deterministic gates、回归测试和真实导出验证，而不是依赖不可解释的“viral”启发式。
- **Performance**：视频处理保持本地并继续利用 GPU；不要为了未来 SaaS 提前引入 server dependency。

## 5. UI 优化（可与上面并行，不依赖云端）

现状：深色 + Ant Design 默认观感，功能在但偏"工程师默认皮肤"，缺乏产品辨识度。
建议流程：
1. **定方向**：`/design-shotgun` 出几版视觉方向对比，或 `/design-consultation` 直接产出一套设计系统 `DESIGN.md`（美学/字体/配色/间距/动效）。
2. **落地**：按 `DESIGN.md` 逐屏重做（首页 / 项目详情 / 设置 / 进度），先抓高频屏。
3. **校验**：`/design-review` 对实跑界面做"设计师之眼"审查并迭代修。

优先级：首页（第一印象）> 项目卡片与进度 > 设置页 > 详情/切片预览。

## 6. 社区入口

公开需求不另建系统。第一阶段用 GitHub Discussions 收想法，用 GitHub Projects「AutoClip Roadmap」公开已经决定要跟的事，费用为零。操作规则见 `docs/COMMUNITY_BOARD.md`。

Quackback 是第二阶段：非开发者的反馈连续多到 Discussions 不够用，并且需要独立的反馈、路线图和更新日志页面时再装。装上之后，确认要做的需求仍写回 GitHub Issue。Featurebase 免费档没有 Agent 能调用的接口，Linear 不适合公众提需求，这两条不走。

## 7. 当前执行顺序

1. **Finish the Retention Engine first** — scroll-stop、curiosity gap、shareability、rewatch/loop，然后做 retention-aware ranking。
2. 用真实 source videos 验证生成的 Shorts，并检查实际导出结果。
3. 根据观察到的结果调整 prompt / weights；不要把这些分数当成 virality 保证。
4. 完成本地 release hardening：Windows 验证、需要时的 signing/notarization、CI、updater 和 UI polish。
5. 核心 pipeline 稳定后，再扩展个人工作流。
6. SaaS、账号、hosted credits、subscriptions 和 payments 保持 deferred，除非产品目标发生变化。

**当前优先级：better output, not a business backend.**

---

> 本文档是活的，随每阶段进展回来更新。配套现状见 `HANDOFF.md`。
