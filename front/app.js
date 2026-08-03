/* ============ Agent Memory Service 测试前端 ============
 * 直接调用后端三个接口：
 *   POST /v1/memory/write  - 写事件 / 触发 Consolidate / 提升候选
 *   POST /v1/memory/read   - 检索记忆
 *   POST /v1/memory/gc     - 评估 / 过期 / 归档 / 删除
 *
 * 租户隔离通过 DevelopmentTenantResolver 接收的头来演示：
 *   X-Development-Tenant-ID   - 租户 ID
 *   X-Development-Principal-ID - 用户 ID
 */

(function () {
    "use strict";

    // ===== DOM 引用 =====
    const $ = (id) => document.getElementById(id);
    const apiBaseEl = $("apiBase");
    const tenantIdEl = $("tenantId");
    const principalIdEl = $("principalId");
    const workspaceIdEl = $("workspaceId");
    const taskIdEl = $("taskId");
    const messagesEl = $("messages");
    const inputEl = $("input");
    const contextViewEl = $("contextView");
    const rawViewEl = $("rawView");
    const panelStatusEl = $("panelStatus");
    const logViewEl = $("logView");

    // ===== 工具：状态 =====
    const setStatus = (text, kind = "") => {
        panelStatusEl.textContent = text;
        panelStatusEl.className = "status " + kind;
    };

    // ===== 工具：日志 =====
    const logs = [];
    const pushLog = (entry) => {
        logs.unshift(entry);
        if (logs.length > 5) logs.pop();
        logViewEl.innerHTML = logs
            .map((l) => {
                const ts = new Date(l.timestamp).toLocaleTimeString();
                const statusCls = l.ok ? "ok" : "err";
                return `<div class="log-entry">
                    [${ts}] <span class="method ${l.method}">${l.method}</span>
                    <span>${l.path}</span>
                    <span class="status ${statusCls}">${l.status}</span>
                    <span>(${l.ms}ms)</span>
                </div>`;
            })
            .join("");
    };

    // ===== 工具：HTTP =====
    const buildHeaders = () => {
        const headers = { "Content-Type": "application/json" };
        const tenantId = tenantIdEl.value.trim();
        const principalId = principalIdEl.value.trim();
        if (tenantId) headers["X-Development-Tenant-ID"] = tenantId;
        if (principalId) headers["X-Development-Principal-ID"] = principalId;
        return headers;
    };

    const apiCall = async (path, body, method = "POST") => {
        const url = `${apiBaseEl.value.trim()}${path}`;
        const headers = buildHeaders();
        const t0 = performance.now();
        try {
            const resp = await fetch(url, {
                method,
                headers,
                body: body ? JSON.stringify(body) : undefined,
            });
            const ms = Math.round(performance.now() - t0);
            const text = await resp.text();
            let json = null;
            try {
                json = text ? JSON.parse(text) : null;
            } catch (_) {
                /* not JSON */
            }
            pushLog({
                method,
                path,
                status: resp.status,
                ok: resp.ok,
                ms,
                timestamp: Date.now(),
            });
            return { ok: resp.ok, status: resp.status, body: json, raw: text };
        } catch (e) {
            const ms = Math.round(performance.now() - t0);
            pushLog({
                method,
                path,
                status: "NETWORK_ERR",
                ok: false,
                ms,
                timestamp: Date.now(),
            });
            return { ok: false, status: 0, body: null, error: String(e) };
        }
    };

    // ===== 聊天 UI =====
    const appendMessage = (role, content, meta = "") => {
        const div = document.createElement("div");
        div.className = `message ${role}`;
        if (meta) {
            const metaDiv = document.createElement("div");
            metaDiv.className = "meta";
            metaDiv.textContent = meta;
            div.appendChild(metaDiv);
        }
        const contentDiv = document.createElement("div");
        contentDiv.textContent = content;
        div.appendChild(contentDiv);
        messagesEl.appendChild(div);
        messagesEl.scrollTop = messagesEl.scrollHeight;
    };

    const clearMessages = () => {
        messagesEl.innerHTML = "";
        contextViewEl.innerHTML = '<div class="empty">尚未检索 — 点 "读取记忆" 查看结果</div>';
        rawViewEl.textContent = "";
        setStatus("就绪");
    };

    // ===== 后端调用：写事件 =====
    const sendEvent = async () => {
        const text = inputEl.value.trim();
        if (!text) return;
        const eventId = `evt_${Date.now()}`;
        const workspaceId = workspaceIdEl.value.trim();
        const taskId = taskIdEl.value.trim();

        appendMessage(
            "user",
            text,
            `event_id=${eventId} | workspace=${workspaceId} | task=${taskId}`
        );
        inputEl.value = "";
        setStatus("写入中…", "busy");

        const result = await apiCall("/v1/memory/write", {
            type: "event",
            idempotency_key: eventId,
            workspace_id: workspaceId,
            event: {
                event_id: eventId,
                event_type: "user_message",
                role: "user",
                content: text,
                source: "chat",
                task_id: taskId,
            },
            signals: {
                token_usage_ratio: 0.6,
                idle_seconds: 0,
            },
        });

        if (result.ok) {
            appendMessage(
                "system",
                `✓ 事件已写入 (status=${result.status})`
            );
            setStatus(`写入成功 (${result.status})`, "ok");
        } else {
            const errMsg = result.body?.error?.message || result.error || "unknown";
            appendMessage("system", `✗ 写入失败: ${result.status} ${errMsg}`);
            setStatus(`写入失败 (${result.status})`, "error");
        }
    };

    // ===== 后端调用：Consolidate Once =====
    const triggerConsolidate = async () => {
        const workspaceId = workspaceIdEl.value.trim();
        setStatus("Consolidate Once 执行中…", "busy");
        appendMessage("system", "→ 触发 Consolidate Once…");

        const result = await apiCall("/v1/memory/write", {
            type: "consolidate",
            workspace_id: workspaceId,
            trigger: "manual",
        });

        if (result.ok) {
            appendMessage(
                "system",
                `✓ Consolidate 完成 (status=${result.status})`
            );
            setStatus("Consolidate 成功", "ok");
        } else {
            const errMsg = result.body?.error?.message || result.error || "unknown";
            appendMessage(
                "system",
                `✗ Consolidate 失败: ${result.status} ${errMsg}`
            );
            setStatus(`Consolidate 失败 (${result.status})`, "error");
        }
    };

    // ===== 后端调用：读取记忆 =====
    const readMemory = async () => {
        const workspaceId = workspaceIdEl.value.trim();
        const taskId = taskIdEl.value.trim();
        setStatus("检索中…", "busy");

        const result = await apiCall("/v1/memory/read", {
            mode: "auto",
            query: inputEl.value.trim() || "最近的对话",
            task_id: taskId,
            workspace_id: workspaceId,
            agent_id: "agent_001",
            top_k: 8,
            token_budget: 1500,
            need_evidence: false,
        });

        // 渲染原始响应
        rawViewEl.textContent = JSON.stringify(result.body, null, 2);

        if (result.ok && result.body) {
            renderContextPackage(result.body);
            const cp = result.body.context_package || {};
            const total =
                (cp.facts?.length || 0) +
                (cp.preferences?.length || 0) +
                (cp.checkpoints?.length || 0) +
                (cp.entities?.length || 0);
            setStatus(`已检索 (${total} 条)`, "ok");
        } else {
            const errMsg = result.body?.error?.message || result.error || "unknown";
            contextViewEl.innerHTML = `<div class="empty">检索失败: ${result.status} ${errMsg}</div>`;
            setStatus(`检索失败 (${result.status})`, "error");
        }
    };

    // ===== 渲染 Context Package =====
    const renderContextPackage = (body) => {
        const cp = body.context_package || {};
        const sections = [
            { key: "facts", title: "事实 Facts", type: "FACT" },
            { key: "preferences", title: "偏好 Preferences", type: "PREFERENCE" },
            { key: "checkpoints", title: "检查点 Checkpoints", type: "CHECKPOINT" },
            { key: "entities", title: "实体 Entities", type: "ENTITY" },
        ];

        let html = "";
        let total = 0;
        for (const sec of sections) {
            const arr = cp[sec.key] || [];
            if (arr.length === 0) continue;
            total += arr.length;
            html += `<h3 style="font-size:12px;color:var(--text-dim);margin-top:8px;margin-bottom:6px">${sec.title} (${arr.length})</h3>`;
            for (const item of arr) {
                const content = item.content || item.summary || item.entity_name || JSON.stringify(item);
                const meta = [];
                if (item.memory_id) meta.push(`id=${item.memory_id}`);
                if (item.confidence != null) meta.push(`conf=${item.confidence.toFixed(2)}`);
                if (item.score != null) meta.push(`score=${item.score.toFixed(2)}`);
                if (item.normalized_key) meta.push(`key=${item.normalized_key}`);
                html += `<div class="memory-card">
                    <span class="type">${sec.type}</span>
                    <div class="content">${escapeHtml(content)}</div>
                    <div class="meta-row">${meta.map((m) => `<span>${escapeHtml(m)}</span>`).join("")}</div>
                </div>`;
            }
        }
        if (total === 0) {
            html = `<div class="empty">该租户下没有匹配的记忆。先发送消息 + 触发 Consolidate 后再读取。</div>`;
        }
        contextViewEl.innerHTML = html;
    };

    const escapeHtml = (s) =>
        String(s)
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;");

    // ===== 后端调用：GC 评估 =====
    const triggerGC = async () => {
        const workspaceId = workspaceIdEl.value.trim();
        setStatus("GC 评估中…", "busy");
        appendMessage("system", "→ 触发 GC 评估（dry_run）…");

        const result = await apiCall("/v1/memory/gc", {
            action: "evaluate",
            workspace_id: workspaceId,
            idempotency_key: `gc_${Date.now()}`,
            dry_run: true,
        });

        if (result.ok) {
            appendMessage(
                "system",
                `✓ GC 评估完成 (status=${result.status})`
            );
            rawViewEl.textContent = JSON.stringify(result.body, null, 2);
            setStatus("GC 完成", "ok");
        } else {
            const errMsg = result.body?.error?.message || result.error || "unknown";
            appendMessage("system", `✗ GC 失败: ${result.status} ${errMsg}`);
            setStatus(`GC 失败 (${result.status})`, "error");
        }
    };

    // ===== 后端健康 =====
    const checkHealth = async () => {
        const base = apiBaseEl.value.trim();
        setStatus("检查后端…", "busy");
        try {
            const [health, ready] = await Promise.all([
                fetch(`${base}/health`).then((r) => r.json()),
                fetch(`${base}/ready`).then((r) => r.json()),
            ]);
            const ok = health.status === "ok" && ready.status === "ready";
            setStatus(
                ok ? "后端就绪" : `后端异常: ${JSON.stringify({ health, ready })}`,
                ok ? "ok" : "error"
            );
        } catch (e) {
            setStatus("无法连接后端: " + e, "error");
        }
    };

    // ===== Tab 切换 =====
    document.querySelectorAll(".tab").forEach((tab) => {
        tab.addEventListener("click", () => {
            document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
            document.querySelectorAll(".tab-content").forEach((c) => {
                c.classList.remove("active");
                c.hidden = true;
            });
            tab.classList.add("active");
            const target = tab.dataset.tab;
            const content = target === "context" ? contextViewEl : rawViewEl;
            content.classList.add("active");
            content.hidden = false;
        });
    });

    // ===== 事件绑定 =====
    $("sendBtn").addEventListener("click", sendEvent);
    $("consolidateBtn").addEventListener("click", triggerConsolidate);
    $("readBtn").addEventListener("click", readMemory);
    $("gcBtn").addEventListener("click", triggerGC);
    $("clearBtn").addEventListener("click", clearMessages);
    $("healthBtn").addEventListener("click", checkHealth);

    inputEl.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendEvent();
        }
    });

    // ===== 初始化 =====
    clearMessages();
    checkHealth();
})();
