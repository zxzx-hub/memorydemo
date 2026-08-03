/* ============ Agent Memory Service 聊天演示前端 ============
 * 主链路：
 *   Browser front -> chatbot /chat -> memorydemo /v1/memory/read + write
 *
 * 调试链路：
 *   Browser front -> memorydemo /v1/memory/read/write/gc
 *
 * 租户隔离通过 DevelopmentTenantResolver 接收的头演示：
 *   X-Development-Tenant-ID
 *   X-Development-Principal-ID
 */

(function () {
    "use strict";

    const $ = (id) => document.getElementById(id);

    const chatbotBaseEl = $("chatbotBase");
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

    let activeSessionId = taskIdEl.value.trim() || "task_001";

    const escapeHtml = (value) =>
        String(value)
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;");

    const setStatus = (text, kind = "") => {
        panelStatusEl.textContent = text;
        panelStatusEl.className = `status ${kind}`;
    };

    const logs = [];
    const pushLog = (entry) => {
        logs.unshift(entry);
        if (logs.length > 8) logs.pop();
        logViewEl.innerHTML = logs
            .map((item) => {
                const ts = new Date(item.timestamp).toLocaleTimeString();
                const statusClass = item.ok ? "ok" : "err";
                return `<div class="log-entry">
                    [${ts}] <span class="method ${item.method}">${item.method}</span>
                    <span>${escapeHtml(item.target)}${escapeHtml(item.path)}</span>
                    <span class="status ${statusClass}">${escapeHtml(item.status)}</span>
                    <span>(${item.ms}ms)</span>
                </div>`;
            })
            .join("");
    };

    const buildHeaders = () => {
        const headers = { "Content-Type": "application/json" };
        const tenantId = tenantIdEl.value.trim();
        const principalId = principalIdEl.value.trim();
        if (tenantId) headers["X-Development-Tenant-ID"] = tenantId;
        if (principalId) headers["X-Development-Principal-ID"] = principalId;
        headers["X-Trace-ID"] = `trace_front_${Date.now()}`;
        return headers;
    };

    const httpCall = async (base, path, body, method = "POST", target = "api") => {
        const url = `${base.replace(/\/+$/, "")}${path}`;
        const t0 = performance.now();
        try {
            const response = await fetch(url, {
                method,
                headers: buildHeaders(),
                body: body ? JSON.stringify(body) : undefined,
            });
            const ms = Math.round(performance.now() - t0);
            const text = await response.text();
            let json = null;
            try {
                json = text ? JSON.parse(text) : null;
            } catch (_) {
                // non-json response
            }
            pushLog({
                target,
                method,
                path,
                status: response.status,
                ok: response.ok,
                ms,
                timestamp: Date.now(),
            });
            return { ok: response.ok, status: response.status, body: json, raw: text };
        } catch (error) {
            const ms = Math.round(performance.now() - t0);
            pushLog({
                target,
                method,
                path,
                status: "NETWORK_ERR",
                ok: false,
                ms,
                timestamp: Date.now(),
            });
            return { ok: false, status: 0, body: null, raw: "", error: String(error) };
        }
    };

    const chatbotCall = (path, body, method = "POST") =>
        httpCall(chatbotBaseEl.value.trim(), path, body, method, "chatbot");

    const memoryApiCall = (path, body, method = "POST") =>
        httpCall(apiBaseEl.value.trim(), path, body, method, "memory-api");

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

    const renderMemoryContextText = (memoryContext) => {
        if (!memoryContext) {
            contextViewEl.innerHTML =
                '<div class="empty">本轮没有检索到可注入聊天机器人的记忆上下文。</div>';
            return;
        }
        contextViewEl.innerHTML = `<div class="memory-card">
            <span class="type">CHATBOT MEMORY CONTEXT</span>
            <div class="content">${escapeHtml(memoryContext)}</div>
        </div>`;
    };

    const renderContextPackage = (body) => {
        const cp = body.context_package || {};
        const sections = [
            { key: "facts", title: "事实 Facts", type: "FACT" },
            { key: "preferences", title: "偏好 Preferences", type: "PREFERENCE" },
            { key: "constraints", title: "约束 Constraints", type: "CONSTRAINT" },
            { key: "decisions", title: "决策 Decisions", type: "DECISION" },
            { key: "progress", title: "进展 Progress", type: "PROGRESS" },
        ];

        let html = "";
        let total = 0;
        for (const section of sections) {
            const items = cp[section.key] || [];
            if (items.length === 0) continue;
            total += items.length;
            html += `<h3 class="section-title">${section.title} (${items.length})</h3>`;
            for (const item of items) {
                const meta = [];
                if (item.memory_id) meta.push(`id=${item.memory_id}`);
                if (item.version) meta.push(`v=${item.version}`);
                if (item.confidence != null) {
                    meta.push(`conf=${Number(item.confidence).toFixed(2)}`);
                }
                if (item.matched_reason) meta.push(item.matched_reason);
                html += `<div class="memory-card">
                    <span class="type">${section.type}</span>
                    <div class="content">${escapeHtml(item.content || "")}</div>
                    <div class="meta-row">
                        ${meta.map((m) => `<span>${escapeHtml(m)}</span>`).join("")}
                    </div>
                </div>`;
            }
        }
        if (cp.task_checkpoint) {
            total += 1;
            html += `<h3 class="section-title">任务恢复 Checkpoint</h3>
                <div class="memory-card">
                    <span class="type">TASK CHECKPOINT</span>
                    <div class="content">${escapeHtml(
                        JSON.stringify(cp.task_checkpoint.resume_context || {}, null, 2)
                    )}</div>
                </div>`;
        }
        contextViewEl.innerHTML =
            html ||
            '<div class="empty">该租户下没有匹配的 active 长期记忆或任务检查点。</div>';
        return total;
    };

    const clearMessages = () => {
        activeSessionId = taskIdEl.value.trim() || `session_${Date.now()}`;
        messagesEl.innerHTML = "";
        contextViewEl.innerHTML =
            '<div class="empty">开始聊天后，这里会显示 chatbot 注入给大模型的记忆上下文。</div>';
        rawViewEl.textContent = "";
        setStatus("就绪");
    };

    const sendChat = async () => {
        const text = inputEl.value.trim();
        if (!text) return;

        activeSessionId = taskIdEl.value.trim() || activeSessionId;
        appendMessage("user", text, `session=${activeSessionId}`);
        inputEl.value = "";
        setStatus("chatbot 思考中…", "busy");

        const result = await chatbotCall("/chat", {
            message: text,
            session_id: activeSessionId,
            workspace_id: workspaceIdEl.value.trim(),
            memory_limit: 8,
            history_limit: 12,
            save_memory: true,
        });

        rawViewEl.textContent = JSON.stringify(result.body, null, 2);

        if (!result.ok || !result.body) {
            const message = result.body?.detail || result.error || "unknown";
            appendMessage("system", `✗ chatbot 调用失败: ${result.status} ${message}`);
            setStatus(`chatbot 失败 (${result.status})`, "error");
            return;
        }

        activeSessionId = result.body.session_id || activeSessionId;
        taskIdEl.value = activeSessionId;
        appendMessage(
            "agent",
            result.body.answer || "",
            `memory_saved=${Boolean(result.body.memory_saved)}`
        );
        if (result.body.memory_save_error) {
            appendMessage("system", `⚠ 记忆写入失败: ${result.body.memory_save_error}`);
        }
        renderMemoryContextText(result.body.memory_context || "");
        setStatus("chatbot 回复完成", result.body.memory_save_error ? "error" : "ok");
    };

    const triggerConsolidate = async () => {
        const workspaceId = workspaceIdEl.value.trim();
        setStatus("Consolidate Once 执行中…", "busy");
        appendMessage("system", "→ 调试：直接触发 memory API Consolidate Once…");

        const result = await memoryApiCall("/v1/memory/write", {
            type: "consolidate",
            workspace_id: workspaceId,
            trigger: "manual",
        });

        rawViewEl.textContent = JSON.stringify(result.body, null, 2);
        if (result.ok) {
            appendMessage("system", `✓ Consolidate 完成 (status=${result.status})`);
            setStatus("Consolidate 成功", "ok");
        } else {
            const message = result.body?.error?.message || result.error || "unknown";
            appendMessage("system", `✗ Consolidate 失败: ${result.status} ${message}`);
            setStatus(`Consolidate 失败 (${result.status})`, "error");
        }
    };

    const readMemory = async () => {
        const workspaceId = workspaceIdEl.value.trim();
        const taskId = taskIdEl.value.trim() || activeSessionId;
        setStatus("直接检索 memory API…", "busy");

        const result = await memoryApiCall("/v1/memory/read", {
            mode: "auto",
            query: inputEl.value.trim() || "最近的对话",
            task_id: taskId,
            workspace_id: workspaceId,
            agent_id: "front_debugger",
            agent_role: "debugger",
            top_k: 8,
            token_budget: 1500,
            need_evidence: false,
        });

        rawViewEl.textContent = JSON.stringify(result.body, null, 2);
        if (result.ok && result.body) {
            const total = renderContextPackage(result.body);
            setStatus(`memory API 已检索 (${total || 0} 条)`, "ok");
        } else {
            const message = result.body?.error?.message || result.error || "unknown";
            contextViewEl.innerHTML = `<div class="empty">检索失败: ${escapeHtml(
                `${result.status} ${message}`
            )}</div>`;
            setStatus(`检索失败 (${result.status})`, "error");
        }
    };

    const triggerGC = async () => {
        setStatus("GC 评估中…", "busy");
        appendMessage("system", "→ 调试：触发 memory API GC 评估（dry_run）…");

        const result = await memoryApiCall("/v1/memory/gc", {
            action: "evaluate",
            idempotency_key: `gc_${Date.now()}`,
            dry_run: true,
        });

        rawViewEl.textContent = JSON.stringify(result.body, null, 2);
        if (result.ok) {
            appendMessage("system", `✓ GC 评估完成 (status=${result.status})`);
            setStatus("GC 完成", "ok");
        } else {
            const message = result.body?.error?.message || result.error || "unknown";
            appendMessage("system", `✗ GC 失败: ${result.status} ${message}`);
            setStatus(`GC 失败 (${result.status})`, "error");
        }
    };

    const checkHealth = async () => {
        setStatus("检查链路…", "busy");
        try {
            const [chatbotHealth, apiHealth, apiReady] = await Promise.all([
                fetch(`${chatbotBaseEl.value.trim()}/health`).then((r) => r.json()),
                fetch(`${apiBaseEl.value.trim()}/health`).then((r) => r.json()),
                fetch(`${apiBaseEl.value.trim()}/ready`).then((r) => r.json()),
            ]);
            rawViewEl.textContent = JSON.stringify(
                { chatbotHealth, apiHealth, apiReady },
                null,
                2
            );
            const ok =
                chatbotHealth.ok === true &&
                chatbotHealth.memory_service_ok === true &&
                apiHealth.status === "ok" &&
                apiReady.status === "ready";
            setStatus(ok ? "chatbot + memory API 就绪" : "链路存在异常", ok ? "ok" : "error");
        } catch (error) {
            setStatus(`无法连接链路: ${error}`, "error");
        }
    };

    document.querySelectorAll(".tab").forEach((tab) => {
        tab.addEventListener("click", () => {
            document.querySelectorAll(".tab").forEach((item) => {
                item.classList.remove("active");
            });
            document.querySelectorAll(".tab-content").forEach((content) => {
                content.classList.remove("active");
                content.hidden = true;
            });
            tab.classList.add("active");
            const content = tab.dataset.tab === "context" ? contextViewEl : rawViewEl;
            content.classList.add("active");
            content.hidden = false;
        });
    });

    $("sendBtn").addEventListener("click", sendChat);
    $("consolidateBtn").addEventListener("click", triggerConsolidate);
    $("readBtn").addEventListener("click", readMemory);
    $("gcBtn").addEventListener("click", triggerGC);
    $("clearBtn").addEventListener("click", clearMessages);
    $("healthBtn").addEventListener("click", checkHealth);

    inputEl.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            sendChat();
        }
    });

    clearMessages();
    checkHealth();
})();
