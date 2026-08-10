# UPGRADE.md — nanobot 升级流程（本地维护专用）

> 生产库：`~/Desktop/AI/13_nanobot`（gateway 运行中）
> 开发库：`~/Desktop/AI/13_nanobot-dev`
> 版本保存地：`github.com/yuanyi1415/Yuanyi-nanobot`（origin）
> 官方上游：`github.com/HKUDS/nanobot`（upstream，只拉不推）

## 一句话机制

**升级永远在 dev 上做，生产库只做"对齐"，永远不直接动。**

## 什么时候升（三个触发时机，满足其一）

1. 官方合入了咱们需要的功能（如 skill 自动注入、plan tool 等）；
2. 攒了 1~2 个月的更新，一次性升；
3. 官方修了咱们踩到的 bug。

官方更新很活跃，但**不值得每次都跟**——没价值就保持现状。

## 升级四步

```bash
# 第 1 步：dev 拉官方更新并合并（冲突在这里解决）
cd ~/Desktop/AI/13_nanobot-dev
git fetch upstream
git merge upstream/main          # 冲突时手工解决，重点看 webui/src/components/thread/、webui/src/lib/

# 第 2 步：验证（后端 + 前端 + 类型）
PYTHONPATH=$PWD ~/Desktop/AI/13_nanobot/.venv/bin/python -m pytest tests/ -q   # 网络类失败(9个)属环境既有问题，非回归
cd webui && node_modules/.bin/vitest run                                        # 前端测试
node_modules/.bin/tsc -p tsconfig.build.json --noEmit                            # 类型检查

# 第 3 步：推版本保存地
cd ~/Desktop/AI/13_nanobot-dev
git add -A && git commit -m "合并：上游 main + 本地修复"
git push origin main            # 若被拒(non-fast-forward)，确认后 force push

# 第 4 步：生产库对齐 + 重启
cd ~/Desktop/AI/13_nanobot
git fetch origin && git reset --hard origin/main
# 重启 gateway 生效（微信凭证在 ~/.nanobot/weixin/，不受影响、无需重新绑定）
```

## 注意事项

- **本地修复与官方冲突**：本地独有补丁集中在 ThreadComposer（per-chat 草稿保存）、subagent 机制（状态条/路由）、研发文档。官方更新若动了这些文件，冲突在 dev 手工合并——**保留两边功能**，不是二选一。
- **官方合入同类功能时**：本地补丁可退役改用官方实现，少维护一份（判断后删除本地对应改动）。
- **force push**：生产库与 dev 历史分叉时，origin main 可能需要 force push（单人仓库安全），执行前确认本地修复内容已完整包含在待推版本里。
- **生产库不直接改代码**：开发一律在 dev，验证通过再对齐生产。
- **微信/通道**：升级重启不碰 `~/.nanobot/` 运行数据，凭证自动恢复。
