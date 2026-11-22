# S4 本地验收清单（Signals P0 出口）

面向：Xiangqi 在 **15–30 篇真实文献** 上走通 Discover → 裁决 → 导出 Markdown。  
本清单不自动化；不调用本仓库以外的服务。

前置：选一个项目，完成摘要与 Claims 抽取（可用已有库）。

## 发现

- [ ] 点击「发现机会」后同时出现两类候选：局限聚类、矛盾（若语料里确实有）。
- [ ] 打开候选可看到证据：论文标题 + quote + 页码；矛盾候选能看到双方。

## 裁决

- [ ] 至少采纳 3 条 Signal，其中至少 1 条局限聚类、1 条矛盾。
- [ ] 「已采纳 Signal」只读展示证据链，刷新后仍在。
- [ ] 否决一条候选后再次「发现机会」：已采纳 Signal 不被覆盖；对应指纹的新候选带「曾被否决 / previously_rejected」。

## 弱候选

- [ ] 弱候选默认隐藏；打开「显示弱候选」才出现。
- [ ] 弱候选主路径没有「采纳」；需勾选允许弱候选，并以 `accept_weak` 确认后才能采纳。

## 导出

- [ ] 在「已采纳 Signal」页点击「导出 Markdown」，下载的 `.md` 可读：标题/陈述、类型（局限聚类 / 矛盾）、证据指针（论文 + quote + 页）；矛盾含双方。
- [ ] 空项目（无已采纳 Signal）导出仍是合法 Markdown，文案说明没有已采纳 Signal，而不是报错。

## 超时（可选）

- [ ] 用实际模型跑 Discover，不应在约 30 秒内因服务端超时而 504（当前同步窗口约 180 秒）。

---

## 云端稳定性核对（2026-11-22，非真人文献验收）

上面的勾选框仍留给 Xiangqi 在真实文献上走。本节只记录本仓库在云端代理环境里用临时库、mock 和示例夹具跑过的自动化结果。规则矛盾检测的测试通过，不表示真实文献上的科学矛盾质量已经被验证。

基线提交：`a215b686ee4592a0fed35781804790a260fdd7c9`（v1.3.0）。

### 复现命令

在仓库根目录。本环境的 Secret Service 会弹出无人应答的钥匙串对话框，`keyring.get_password` 会一直阻塞，pytest-timeout 的 signal 模式也拉不回来。跑设置相关测试前设置空钥匙串后端：

```bash
export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring
python3 -m pytest backend/tests -q --tb=short -p no:cacheprovider \
  --ignore=backend/tests/run_adjudication_verify.py
cd frontend && npm run build
```

`run_adjudication_verify.py` 与 `test_adjudication.py` 是手工程序（后者 `__test__ = False`），不是 pytest 套件。

### 计数

| 轮次 | 命令范围 | 结果 |
|------|----------|------|
| 基线，非 integration | `pytest … -m "not integration"` | **2 failed / 190 passed / 2 deselected**（2.40s） |
| 基线，integration | `pytest … -m integration` | **2 passed / 192 deselected**（0.55s） |
| 基线合计（与 2026-08 的 192 passed / 2 failed 一致） | 上面两次相加 | **192 passed / 2 failed / 0 skipped** |
| 基线失败项 | `test_extract_success_sse`、`test_parse_pdf_success` | 夹具全文 45 与 80 字符，低于 `SCANNED_DOC_MIN_CHARS=500`，被判定为扫描版（提取 HTTP 400，解析 `is_scanned is True`） |
| 基线前端 | `cd frontend && npm run build`（`tsc -b && vite build`） | exit 0 |
| 本轮之后 | 全量 pytest（含 integration，无 `-m`） | **201 passed / 0 failed / 0 skipped**（2.46s，184 warnings） |
| 本轮之后前端 | 同一 `npm run build` | exit 0（前端源码未改） |

多出来的 7 个测试：扫描阈值边界、低于阈值的提取必须 400、低于阈值的解析必须 `is_scanned`、已采纳矛盾 Signal 在删除原 claim 后导出仍保留双方 quote 与页码。原先那 2 个失败用例改为使用达到阈值的夹具，断言仍是成功路径（HTTP 200 + SSE，`is_scanned is False`）。扫描判定阈值没有改。

### 本轮核对过的行为

- [x] 局限聚类与规则矛盾候选可同时落在同一项目（mock 聚类 + 夹具 claims）
- [x] 采纳写入 project / type / statement / evidence snapshot；否决不产生已采纳 Signal
- [x] 弱候选无 `accept_weak` 时 HTTP 400；主路径候选不需要该标志
- [x] 再次 discover 不覆盖已采纳 Signal；同一指纹的新候选 `previously_rejected=true`
- [x] 导出只含本项目已采纳 Signal；矛盾含双方论文、quote、页码；空项目返回合法 Markdown 而不是 500；跨项目不泄漏
- [x] 删除原 claim 后，导出仍使用采纳时冻结的快照
- [x] 临时文件库 `alembic upgrade head` 到 `l2m3n4o5p6q7`，`signals.evidence_snapshot` 可写入并在重新打开后读回

### 未验证（不要当成已通过）

- [ ] 15–30 篇真实文献上的 Discover → 裁决 → 导出
- [ ] 真实模型调用，以及矛盾检测的科学质量
- [ ] PyInstaller onedir / NSIS 安装包（本轮没有执行 `npm run electron:build`）
- [ ] 打包后的 `%APPDATA%` 持久化，以及 Windows 上的安装与钥匙串
- [ ] 可选的 180 秒真实模型超时项

### 打包前置（尚未构建）

Windows 安装包需要在 Windows x64 上执行 `npm run electron:build`（前端 build + `backend/backend.spec` 的 PyInstaller + electron-builder NSIS）。`requirements.txt` 没有钉死 PyInstaller，构建机需要另装。本环境是 Linux，不能把这次核对说成已经打出安装包。
