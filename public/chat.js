    function keyFromPath() {
      const parts = location.pathname.replace(/^\/+/, "").split("/").filter(Boolean);
      if (parts[0] === "widget" && parts[1]) return decodeURIComponent(parts[1]);
      return decodeURIComponent(parts[0] || "");
    }

    const pathKey = keyFromPath();
    const params = new URLSearchParams(location.search);
    const sourceCode = params.get("src") || "";
    const visitorKey = `webchat:visitor:${pathKey}`;
    const sessionKey = `webchat:session:${pathKey}`;
    const streamTokenKey = `webchat:stream_token:${pathKey}`;
    const visitorId = getOrCreate(visitorKey);
    const storedSession = readStoredSession();
    let sessionId = storedSession.sessionId;
    let streamToken = storedSession.streamToken;
    let stream = null;
    let lastEventId = 0;
    const seenIds = new Set();
    const seenQueue = [];
    const notifiedEventIds = new Set();
    const notifiedEventQueue = [];
    let notificationPermissionRequested = false;
    let audioCtx = null;
    let unreadCount = 0;
    let parentNotificationPermission = "";
    let swRegistration = null;
    let swRegistering = null;
    let widgetEnabled = false;
    let agentWaitBox = null;
    let agentWaitTimer = null;
    const AGENT_WAIT_TIMEOUT_MS = 3 * 60 * 1000;
    const embeddedFrame = window.parent && window.parent !== window;

    if ("scrollRestoration" in history) {
      history.scrollRestoration = "manual";
    }

    // SW 注册不需要通知权限,提前注册好,避免后台收到消息时还没准备好。
    if ("serviceWorker" in navigator) {
      ensureServiceWorker();
    }

    // 调试面板: 给 iframe src 或地址栏加 ?debug=1 即可看到通知/SW 状态,排查移动端弹不出通栏的问题。
    const debugMode = params.get("debug") === "1";
    let debugEl = null;
    if (debugMode) {
      debugEl = document.getElementById("debug");
      if (debugEl) {
        debugEl.hidden = false;
        const btnTest = document.createElement("button");
        btnTest.type = "button";
        btnTest.textContent = "测试通知";
        btnTest.addEventListener("click", () => {
          showLocalNotification("测试通知", {
            body: "如果你看到通栏弹窗,说明 SW 通知正常工作",
            tag: "webchat-test"
          }).then((ok) => {
            debugLog(`测试通知调用结果: ${ok ? "已发出" : "失败(SW/权限均不可用)"}`);
          });
        });
        const btnRefresh = document.createElement("button");
        btnRefresh.type = "button";
        btnRefresh.textContent = "刷新状态";
        btnRefresh.addEventListener("click", () => refreshDebugInfo());
        debugEl.appendChild(btnTest);
        debugEl.appendChild(btnRefresh);
        const pre = document.createElement("div");
        pre.id = "debug-info";
        debugEl.appendChild(pre);
        refreshDebugInfo();
      }
    }
    async function refreshDebugInfo() {
      if (!debugEl) return;
      const info = {
        embedded: embeddedFrame,
        document_hidden: document.hidden,
        visibility: document.visibilityState,
        notification_api: "Notification" in window,
        notification_permission: ("Notification" in window) ? Notification.permission : "n/a",
        sw_api: "serviceWorker" in navigator,
        sw_state: "未注册"
      };
      if ("serviceWorker" in navigator) {
        try {
          const reg = await navigator.serviceWorker.getRegistration("/");
          if (reg) {
            const w = reg.active || reg.waiting || reg.installing;
            info.sw_state = w ? w.state : "registered-no-worker";
            info.sw_scope = reg.scope;
          }
        } catch (e) {
          info.sw_state = `error: ${e.message}`;
        }
      }
      const pre = document.getElementById("debug-info");
      if (pre) pre.textContent = JSON.stringify(info, null, 2);
    }
    function debugLog(msg) {
      if (!debugEl) return;
      const pre = document.getElementById("debug-info");
      if (pre) pre.textContent = `[${new Date().toLocaleTimeString()}] ${msg}\n\n` + pre.textContent;
    }
    document.addEventListener("visibilitychange", () => {
      if (debugMode) refreshDebugInfo();
    });

    // 跨域通知父页面（用于 iframe 挂件场景）
    function postParent(type, payload = {}) {
      if (!embeddedFrame) return;
      try {
        window.parent.postMessage(
          {
            source: "webchat-kefu",
            type: type,
            key: pathKey,
            session_id: sessionId,
            url: location.href,
            ...payload
          },
          '*'
        );
      } catch (_) {}
    }

    window.addEventListener("message", (event) => {
      const data = event.data || {};
      if (!data || data.source !== "webchat-kefu-parent") return;
      if (data.type === "notification_permission") {
        parentNotificationPermission = data.permission || "";
        // 父页面授权后,iframe 通过权限委派也立刻为 granted,这时把 SW 准备好。
        if (parentNotificationPermission === "granted" &&
            "Notification" in window && Notification.permission === "granted") {
          ensureServiceWorker();
        }
        refreshNotificationHint();
      }
    });

    function rememberLimited(set, queue, id, limit = 200) {
      if (!id) return false;
      if (set.has(id)) return true;
      set.add(id);
      queue.push(id);
      if (queue.length > limit) set.delete(queue.shift());
      return false;
    }

    function alreadySeen(id) {
      return rememberLimited(seenIds, seenQueue, id ? String(id) : "");
    }

    function markSeen(id) {
      const value = id ? String(id) : "";
      if (value) rememberLimited(seenIds, seenQueue, value);
    }

    function markNotified(id) {
      const value = id ? String(id) : "";
      if (value) rememberLimited(notifiedEventIds, notifiedEventQueue, value);
    }

    // 仅允许 http/https/相对路径作为媒体 URL,杜绝 javascript: 等危险协议。
    function authedMediaUrl(fileId) {
      if (!fileId || !sessionId || !streamToken) return "";
      const q = `session_id=${encodeURIComponent(sessionId)}&token=${encodeURIComponent(streamToken)}`;
      return `/api/media/${encodeURIComponent(fileId)}?${q}`;
    }

    function safeMediaUrl(u, fallbackFileId) {
      const v = (u || "").trim();
      if (v && /^(https?:|\/)/i.test(v)) {
        if (v.startsWith("/api/media/") && !/[?&]token=/.test(v)) {
          return authedMediaUrl(fallbackFileId) || "";
        }
        return v;
      }
      if (fallbackFileId) return authedMediaUrl(fallbackFileId);
      return "";
    }

    const messages = document.getElementById("messages");
    const input = document.getElementById("input");
    const sendBtn = document.getElementById("sendBtn");
    const quickReplies = document.getElementById("quickReplies");
    const displayName = document.getElementById("displayName");
    const statusText = document.getElementById("statusText");
    const notice = document.getElementById("notice");

    function cryptoRandom() {
      if (window.crypto && crypto.randomUUID) return crypto.randomUUID().replaceAll("-", "");
      return `${Date.now()}${Math.random().toString(16).slice(2)}`;
    }

    function getOrCreate(key) {
      let value = localStorage.getItem(key);
      if (!value) {
        value = cryptoRandom();
        localStorage.setItem(key, value);
      }
      return value;
    }

    function resetStoredSession() {
      try {
        localStorage.removeItem(sessionKey);
        localStorage.removeItem(streamTokenKey);
      } catch (_) {}
    }

    function readStoredSession() {
      let storedSessionId = "";
      let storedToken = "";
      try {
        storedSessionId = localStorage.getItem(sessionKey) || "";
        storedToken = localStorage.getItem(streamTokenKey) || "";
      } catch (_) {}
      if (storedSessionId && !storedToken) {
        resetStoredSession();
        storedSessionId = "";
      } else if (!storedSessionId && storedToken) {
        resetStoredSession();
        storedToken = "";
      }
      return {
        sessionId: storedSessionId || cryptoRandom(),
        streamToken: storedToken
      };
    }

    function persistSession() {
      try { localStorage.setItem(sessionKey, sessionId); } catch (_) {}
    }

    function persistStreamToken() {
      try {
        if (streamToken) localStorage.setItem(streamTokenKey, streamToken);
        else localStorage.removeItem(streamTokenKey);
      } catch (_) {}
    }

    function notificationSupported() {
      return "Notification" in window;
    }

    // 注册 Service Worker:移动端 Chrome 仅通过 SW 才能弹「通栏通知」,
    // 普通的 new Notification(...) 在 Android Chrome 上不显示横幅。
    function ensureServiceWorker() {
      if (swRegistration) return Promise.resolve(swRegistration);
      if (swRegistering) return swRegistering;
      if (!("serviceWorker" in navigator)) return Promise.resolve(null);
      swRegistering = navigator.serviceWorker.register("/sw.js", { scope: "/" }).then(
        (reg) => {
          swRegistration = reg;
          return reg;
        },
        () => null
      );
      return swRegistering;
    }

    function showNotice(text, onClick) {
      if (!notice) return;
      notice.textContent = text;
      notice.dataset.show = "1";
      notice.onclick = () => {
        if (typeof onClick === "function") onClick();
      };
    }

    function hideNotice() {
      if (!notice) return;
      notice.dataset.show = "";
      notice.onclick = null;
    }

    function refreshNotificationHint() {
      if (embeddedFrame) {
        if (parentNotificationPermission === "granted") {
          hideNotice();
          return;
        }
        if (parentNotificationPermission === "denied") {
          showNotice("当前页面通知被禁用，新消息将仅以声音提示。");
          return;
        }
        showNotice("点这里开启新消息提醒（由当前页面弹出授权）", () => {
          requestNotificationPermission(true);
        });
        return;
      }
      if (!notificationSupported()) {
        hideNotice();
        return;
      }
      if (Notification.permission === "granted") {
        hideNotice();
        return;
      }
      if (Notification.permission === "denied") {
        showNotice("浏览器通知被禁用，新消息将仅以声音提示。");
        return;
      }
      showNotice("点这里开启新消息提醒（声音 + 浏览器通知）", () => {
        requestNotificationPermission(true);
      });
    }

    function requestNotificationPermission(force) {
      if (embeddedFrame) {
        if (!notificationPermissionRequested || force) {
          notificationPermissionRequested = true;
          postParent("request_notification_permission", {
            title: displayName.textContent || pathKey || "在线客服"
          });
        }
        // 现代浏览器对 iframe 启用「权限委派 (Permission Delegation)」:
        // 父页面用 allow="notifications" 委派后,iframe 自身的
        // Notification.permission 会自动等于父页面的授权状态,不会再弹第二个框。
        // 所以这里只「读」权限并按需注册 SW,不再主动 requestPermission()。
        if (notificationSupported() && Notification.permission === "granted") {
          ensureServiceWorker();
        }
        refreshNotificationHint();
        return;
      }
      if (!notificationSupported()) return;
      if (Notification.permission === "granted") {
        ensureServiceWorker();
        refreshNotificationHint();
        return;
      }
      if (Notification.permission !== "default") {
        refreshNotificationHint();
        return;
      }
      if (notificationPermissionRequested && !force) return;
      notificationPermissionRequested = true;
      try {
        const request = Notification.requestPermission();
        if (request && typeof request.then === "function") {
          request.then((p) => {
            if (p === "granted") ensureServiceWorker();
            refreshNotificationHint();
          }).catch(() => refreshNotificationHint());
        } else {
          refreshNotificationHint();
        }
      } catch (_) {
        refreshNotificationHint();
      }
    }

    function ensureAudio() {
      if (audioCtx) return audioCtx;
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return null;
      try {
        audioCtx = new Ctx();
      } catch (_) {
        audioCtx = null;
      }
      return audioCtx;
    }

    function playDing() {
      const ctx = ensureAudio();
      if (!ctx) return;
      try {
        if (ctx.state === "suspended" && typeof ctx.resume === "function") {
          ctx.resume().catch(() => {});
        }
        const now = ctx.currentTime;
        const master = ctx.createGain();
        master.gain.value = 0.85;
        master.connect(ctx.destination);
        // 两声叮咚:880Hz → 1320Hz,音量更大、更易听见。
        const tones = [
          { freq: 880, start: 0.0, end: 0.28, peak: 0.55 },
          { freq: 1320, start: 0.18, end: 0.5, peak: 0.5 }
        ];
        tones.forEach((t) => {
          const osc = ctx.createOscillator();
          const gain = ctx.createGain();
          osc.type = "sine";
          osc.frequency.setValueAtTime(t.freq, now + t.start);
          gain.gain.setValueAtTime(0.0001, now + t.start);
          gain.gain.exponentialRampToValueAtTime(t.peak, now + t.start + 0.02);
          gain.gain.exponentialRampToValueAtTime(0.0001, now + t.end);
          osc.connect(gain).connect(master);
          osc.start(now + t.start);
          osc.stop(now + t.end + 0.02);
        });
      } catch (_) {}
    }

    function notificationBody(message) {
      const text = (message.text || message.caption || message.body || "").trim();
      if (text) return text.length > 80 ? `${text.slice(0, 80)}...` : text;
      if (message.kind === "photo") return "客服发来一条图片消息";
      if (message.kind === "video") return "客服发来一条视频消息";
      if (message.kind === "document") return "客服发来一个文件";
      if (message.kind === "note") return "客服发来一条笔记";
      return "客服发来一条新消息";
    }

    function scrollToLatest() {
      requestAnimationFrame(() => {
        messages.scrollTop = messages.scrollHeight;
      });
    }

    function clearAgentWaitStatus() {
      if (agentWaitTimer) {
        clearTimeout(agentWaitTimer);
        agentWaitTimer = null;
      }
      if (agentWaitBox) {
        agentWaitBox.remove();
        agentWaitBox = null;
      }
    }

    function showAgentWaitStatus() {
      if (agentWaitBox) {
        scrollToLatest();
        return;
      }

      agentWaitBox = document.createElement("div");
      agentWaitBox.className = "msg agent agent-wait";
      agentWaitBox.setAttribute("aria-live", "polite");

      const text = document.createElement("span");
      text.textContent = "正在呼叫客服，请稍等";
      const dots = document.createElement("span");
      dots.className = "wait-dots";
      dots.setAttribute("aria-hidden", "true");
      dots.innerHTML = "<i></i><i></i><i></i>";

      agentWaitBox.appendChild(text);
      agentWaitBox.appendChild(dots);
      messages.appendChild(agentWaitBox);
      scrollToLatest();

      agentWaitTimer = setTimeout(() => {
        clearAgentWaitStatus();
        appendMessage({
          role: "agent",
          kind: "text",
          text: "客服暂时不在线，请留言",
          from_name: displayName.textContent || ""
        });
      }, AGENT_WAIT_TIMEOUT_MS);
    }

    async function showLocalNotification(title, options) {
      // 优先用 Service Worker 显示通知 —— 移动端浏览器(尤其 Android Chrome)
      // 只有通过 ServiceWorkerRegistration.showNotification 才会出现「通栏」横幅。
      let reg = swRegistration;
      if (!reg && "serviceWorker" in navigator) {
        try { reg = await ensureServiceWorker(); } catch (_) {}
      }
      if (!reg && "serviceWorker" in navigator) {
        try { reg = await navigator.serviceWorker.ready; } catch (_) {}
      }
      if (reg && typeof reg.showNotification === "function") {
        try {
          await reg.showNotification(title, options);
          return true;
        } catch (_) {}
      }
      try {
        const n = new Notification(title, options);
        n.onclick = () => { window.focus(); n.close(); };
        return true;
      } catch (_) {
        return false;
      }
    }

    function maybeNotifyAgentMessage(message) {
      if (message.role !== "agent") return;
      const eventId = message.id ? String(message.id) : "";
      if (rememberLimited(notifiedEventIds, notifiedEventQueue, eventId)) return;

      const title = displayName.textContent || pathKey || "在线客服";
      const body = notificationBody(message);
      const tag = eventId ? `webchat:${pathKey}:${sessionId}:${eventId}` : `webchat:${pathKey}:${sessionId}`;

      // 前台:只播放声音。
      if (!document.hidden) {
        playDing();
        return;
      }

      // 后台:优先用 iframe 自己的 SW 通知(移动端能弹通栏);失败再让父页面兜底。
      const ownGranted = notificationSupported() && Notification.permission === "granted";
      let triedLocal = false;
      if (ownGranted) {
        triedLocal = true;
        showLocalNotification(title, {
          body,
          tag,
          renotify: true,
          requireInteraction: false
        }).then((ok) => {
          if (!ok) {
            postParent("new_message", { title, body, tag, page_hidden: true });
          }
        }).catch(() => {
          postParent("new_message", { title, body, tag, page_hidden: true });
        });
      } else {
        postParent("new_message", { title, body, tag, page_hidden: true });
      }
      playDing();
    }

    function prependMessage(message) {
      const role = message.role || "system";
      const box = document.createElement("div");
      box.className = `msg ${role}`;
      if (message.from_name) {
        const from = document.createElement("div");
        from.className = "from";
        from.textContent = message.from_name;
        box.appendChild(from);
      }
      renderContent(box, message);
      messages.insertBefore(box, messages.firstChild);
    }

    function appendMessage(message, options = {}) {
      if (alreadySeen(message.id)) return;
      const role = message.role || "system";
      if (role === "agent" && options.notify) {
        clearAgentWaitStatus();
      }
      const box = document.createElement("div");
      box.className = `msg ${role}`;

      if (message.from_name) {
        const from = document.createElement("div");
        from.className = "from";
        from.textContent = message.from_name;
        box.appendChild(from);
      }

      renderContent(box, message);
      messages.appendChild(box);
      scrollToLatest();
      if (message.id) lastEventId = Math.max(lastEventId, Number(message.id) || 0);
      if (options.notify) {
        maybeNotifyAgentMessage(message);
        // 页面隐藏时累计未读数并通知父页面。
        if (message.role === "agent" && document.hidden) {
          unreadCount += 1;
          postParent("unread_update", { unread: unreadCount });
        }
      } else if (message.id) {
        // 历史回放 / 本地回显的消息：登记到通知去重表，避免后续 SSE 重连重复响铃。
        markNotified(message.id);
      }
    }

    function renderContent(box, message) {
      const kind = message.kind || "text";
      if (kind === "photo") {
        renderPhoto(box, message);
      } else if (kind === "video") {
        renderVideo(box, message);
      } else if (kind === "document") {
        renderDocument(box, message);
      } else if (kind === "note") {
        if (message.title) renderText(box, message.title);
        if (message.body) renderText(box, message.body);
        const grid = document.createElement("div");
        grid.className = "note-grid";
        (message.media || []).forEach((item) => renderMediaItem(grid, item));
        if (grid.children.length) box.appendChild(grid);
      } else {
        renderText(box, message.text || "");
      }

      if (message.caption) renderText(box, message.caption);
    }

    function renderText(box, text) {
      const div = document.createElement("div");
      div.textContent = text || "";
      box.appendChild(div);
    }

    function renderExpired(box, label) {
      const div = document.createElement("div");
      div.className = "expired";
      div.textContent = label;
      box.appendChild(div);
    }

    function renderPhoto(box, message) {
      if (message.media_expired) return renderExpired(box, "图片已过期");
      const img = document.createElement("img");
      img.className = "media";
      img.alt = "图片";
      img.src = safeMediaUrl(message.media_url, message.file_id);
      img.onerror = () => {
        img.replaceWith(Object.assign(document.createElement("div"), { className: "expired", textContent: "图片已过期" }));
      };
      box.appendChild(img);
    }

    function renderVideo(box, message) {
      if (message.media_expired) return renderExpired(box, "视频已过期");
      const video = document.createElement("video");
      video.className = "media";
      video.controls = true;
      video.src = safeMediaUrl(message.media_url, message.file_id);
      box.appendChild(video);
    }

    function renderDocument(box, message) {
      const a = document.createElement("a");
      a.className = "file-card";
      if (message.media_expired) {
        a.removeAttribute("href");
        a.textContent = "文件已过期";
      } else {
        const href = safeMediaUrl(message.media_url, message.file_id);
        if (href) {
          a.href = href;
          a.target = "_blank";
          a.rel = "noopener noreferrer";
        }
        a.textContent = message.file_name || "打开文件";
      }
      box.appendChild(a);
    }

    function renderMediaItem(grid, item) {
      const wrap = document.createElement("div");
      if (item.media_expired) {
        wrap.className = "expired";
        wrap.textContent = item.type === "video" ? "视频已过期" : item.type === "document" ? "文件已过期" : "图片已过期";
        grid.appendChild(wrap);
        return;
      }
      if (item.type === "video") {
        const video = document.createElement("video");
        video.className = "media";
        video.controls = true;
        video.src = safeMediaUrl(item.media_url, item.file_id);
        grid.appendChild(video);
      } else if (item.type === "document") {
        const a = document.createElement("a");
        a.className = "file-card";
        const href = safeMediaUrl(item.media_url, item.file_id);
        if (href) {
          a.href = href;
          a.target = "_blank";
          a.rel = "noopener noreferrer";
        }
        a.textContent = "打开文件";
        grid.appendChild(a);
      } else {
        const img = document.createElement("img");
        img.className = "media";
        img.alt = "图片";
        img.src = safeMediaUrl(item.media_url, item.file_id);
        grid.appendChild(img);
      }
    }

    async function loadWidget() {
      const url = `/widget/${encodeURIComponent(pathKey)}?visitor_id=${encodeURIComponent(visitorId)}${sourceCode ? `&src=${encodeURIComponent(sourceCode)}` : ""}`;
      const resp = await fetch(url);
      const data = await resp.json();
      if (!data.ok) {
        statusText.textContent = "入口不可用";
        appendMessage({ role: "system", kind: "text", text: "客服入口不存在或暂不可用。" });
        return;
      }

      displayName.textContent = data.display_name || pathKey || "在线客服";
      widgetEnabled = Boolean(data.enabled);
      statusText.textContent = widgetEnabled ? "在线咨询" : "离线留言";
      postParent("ready", {
        title: displayName.textContent || pathKey || "在线客服",
        notification_permission: embeddedFrame ? parentNotificationPermission : (notificationSupported() ? Notification.permission : "unsupported")
      });

      const welcomeText = (data.welcome_text || "").trim();
      const offlineMsg = (data.offline_msg || "").trim();
      renderQuickReplies(data.quick_replies || [], data.display_name || "");
      await loadHistory();
      // 欢迎语固定在历史顶部；下班留言仅在客户发消息后由后端写入历史，不在此展示
      if (welcomeText) {
        prependMessage({ role: "agent", kind: "text", text: welcomeText, from_name: data.display_name || "" });
      }
      connectStream();
      refreshNotificationHint();
    }

    function renderQuickReplies(items, agentName) {
      quickReplies.innerHTML = "";
      if (!items.length) {
        quickReplies.hidden = true;
        return;
      }
      items.forEach((item) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.title = item.title;
        btn.textContent = item.title;
        btn.addEventListener("click", () => {
          // 触发用户手势上下文：顺便申请通知权限并解锁 AudioContext。
          requestNotificationPermission();
          ensureAudio();
          appendMessage({ role: "user", kind: "text", text: item.title });
          // 自动回复以「客服回复」的正常样式显示，而不是系统提示。
          appendMessage({
            role: "agent",
            kind: "text",
            text: item.answer,
            from_name: agentName || displayName.textContent || ""
          });
        });
        quickReplies.appendChild(btn);
      });
      quickReplies.hidden = false;
    }

    async function loadHistory() {
      if (!streamToken) return;
      const q = `session_id=${encodeURIComponent(sessionId)}&token=${encodeURIComponent(streamToken)}`;
      const resp = await fetch(`/api/history/${encodeURIComponent(pathKey)}?${q}`);
      if (!resp.ok) return;
      const data = await resp.json();
      if (!data.ok) return;
      messages.innerHTML = "";
      if (data.truncated) {
        appendMessage({ role: "system", kind: "text", text: "— 仅显示最近的消息,更早的记录已不可见 —" });
      }
      (data.events || []).forEach((ev) => appendMessage(ev));
      scrollToLatest();
      setTimeout(scrollToLatest, 50);
    }

    function connectStream(force) {
      if (!streamToken) return;
      // 复用已打开的连接(避免每次发完消息都重连导致后端连接数翻倍)。
      if (stream && stream.readyState !== 2 && !force) return;
      if (stream) stream.close();
      let url = `/api/stream/${encodeURIComponent(sessionId)}?since_id=${lastEventId}`;
      if (streamToken) url += `&token=${encodeURIComponent(streamToken)}`;
      stream = new EventSource(url);
      stream.addEventListener("msg", (event) => {
        try {
          const payload = JSON.parse(event.data);
          appendMessage(payload, { notify: true });
        } catch (_) {}
      });
      stream.onerror = () => {
        if (stream.readyState === 2) {
          setTimeout(() => connectStream(true), 5000);
        }
      };
    }

    async function sendMessage() {
      const text = input.value.trim();
      if (!text) return;
      // 用户主动发送是最稳定的「用户手势」时机：解锁 AudioContext 并申请通知权限。
      ensureAudio();
      requestNotificationPermission();
      input.value = "";
      appendMessage({ role: "user", kind: "text", text });

      const resp = await fetch(`/api/msg/${encodeURIComponent(pathKey)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          visitor_id: visitorId,
          source_code: sourceCode,
          token: streamToken,
          text
        })
      });
      let data;
      try {
        data = await resp.json();
      } catch (_) {
        clearAgentWaitStatus();
        appendMessage({ role: "system", kind: "text", text: "服务器响应异常，请稍后重试。" });
        return;
      }
      if (!data.ok) {
        clearAgentWaitStatus();
        if (resp.status === 401 && data.error === "BAD_SESSION_TOKEN") {
          resetStoredSession();
          sessionId = cryptoRandom();
          streamToken = "";
          if (stream) { stream.close(); stream = null; }
          appendMessage({ role: "system", kind: "text", text: "会话已过期，请重新发送。" });
          return;
        }
        appendMessage({ role: "system", kind: "text", text: `发送失败：${data.error || "UNKNOWN"}` });
        return;
      }
      if (data.event_id) {
        markSeen(data.event_id);
        lastEventId = Math.max(lastEventId, Number(data.event_id) || 0);
      }
      const newSessionId = data.session_id || sessionId;
      const sessionChanged = newSessionId !== sessionId;
      sessionId = newSessionId;
      persistSession();
      const newToken = data.session_access_token || data.stream_token || "";
      if (newToken) {
        streamToken = newToken;
        persistStreamToken();
      }
      if (data.created && Number(data.enabled) === 1) {
        showAgentWaitStatus();
      } else {
        clearAgentWaitStatus();
      }
      // 只有 session 变化或 stream 已关闭时才重连。
      if (sessionChanged || !stream || stream.readyState === 2) connectStream(true);
    }

    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) {
        connectStream();
        // 回到页面时重置未读计数
        if (unreadCount > 0) {
          unreadCount = 0;
          postParent("unread_update", { unread: 0 });
        }
      }
    });
    window.addEventListener("pagehide", () => {
      if (stream) { stream.close(); stream = null; }
    });

    // 任意一次用户点击/按键都视为手势，用于解锁 AudioContext 并尝试申请通知权限。
    function bootstrapGesture() {
      ensureAudio();
      requestNotificationPermission();
    }
    document.addEventListener("click", bootstrapGesture, { once: false, passive: true });
    document.addEventListener("touchstart", bootstrapGesture, { once: false, passive: true });
    input && input.addEventListener("focus", bootstrapGesture);

    const attachBtn = document.getElementById("attachBtn");
    const fileInput = document.getElementById("fileInput");

    async function uploadFile(file) {
      if (!file) return;
      requestNotificationPermission();
      persistSession();

      // show preview immediately
      const isImage = file.type.startsWith("image/");
      let previewEl = null;
      const box = document.createElement("div");
      box.className = "msg user upload-sending";
      if (isImage) {
        const objUrl = URL.createObjectURL(file);
        previewEl = document.createElement("img");
        previewEl.className = "upload-preview";
        previewEl.src = objUrl;
        previewEl.alt = file.name;
        box.appendChild(previewEl);
      } else {
        const nameEl = document.createElement("div");
        nameEl.textContent = `📎 ${file.name}`;
        box.appendChild(nameEl);
      }
      const hint = document.createElement("div");
      hint.style.cssText = "font-size:12px;color:#999;margin-top:4px";
      hint.textContent = "发送中…";
      box.appendChild(hint);
      messages.appendChild(box);
      messages.scrollTop = messages.scrollHeight;

      const formData = new FormData();
      formData.append("file", file);
      formData.append("session_id", sessionId);
      formData.append("visitor_id", visitorId);
      if (streamToken) formData.append("token", streamToken);

      let data;
      try {
        const resp = await fetch(`/api/upload/${encodeURIComponent(pathKey)}`, {
          method: "POST",
          body: formData,
        });
        data = await resp.json();
        if (!data.ok) {
          hint.textContent = `上传失败：${data.error || "UNKNOWN"}`;
          box.classList.remove("upload-sending");
          if (previewEl) URL.revokeObjectURL(previewEl.src);
          return;
        }
      } catch (_) {
        hint.textContent = "上传失败，请检查网络";
        box.classList.remove("upload-sending");
        if (previewEl) URL.revokeObjectURL(previewEl.src);
        return;
      }

      // success — replace placeholder with real event
      box.remove();
      if (previewEl) URL.revokeObjectURL(previewEl.src);

      const newSessionId = data.session_id || sessionId;
      const sessionChanged = newSessionId !== sessionId;
      sessionId = newSessionId;
      persistSession();
      const newToken = data.session_access_token || data.stream_token || "";
      if (newToken) { streamToken = newToken; persistStreamToken(); }

      if (data.event) {
        appendMessage(data.event);
        if (data.event.id) {
          markSeen(data.event.id);
          lastEventId = Math.max(lastEventId, Number(data.event.id) || 0);
        }
      }
      if (sessionChanged || !stream || stream.readyState === 2) connectStream(true);
    }

    attachBtn.addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", () => {
      const file = fileInput.files && fileInput.files[0];
      fileInput.value = "";
      if (file) uploadFile(file);
    });

    sendBtn.addEventListener("click", sendMessage);
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
      }
    });

    loadWidget().catch(() => {
      statusText.textContent = "连接失败";
      appendMessage({ role: "system", kind: "text", text: "无法连接客服服务，请稍后再试。" });
    });
