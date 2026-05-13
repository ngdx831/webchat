const pathKey = decodeURIComponent(location.pathname.replace(/^\/+/, "").split("/")[0] || "");
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

    function requestNotificationPermission() {
      if (!notificationSupported()) return;
      if (Notification.permission !== "default") return;
      if (notificationPermissionRequested) return;
      notificationPermissionRequested = true;
      const request = Notification.requestPermission();
      if (request && typeof request.catch === "function") request.catch(() => {});
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

    function maybeNotifyAgentMessage(message) {
      if (message.role !== "agent") return;
      if (!document.hidden) return;
      if (!notificationSupported()) return;
      if (Notification.permission !== "granted") return;

      const eventId = message.id ? String(message.id) : "";
      if (rememberLimited(notifiedEventIds, notifiedEventQueue, eventId)) return;

      try {
        const notification = new Notification(displayName.textContent || pathKey || "在线客服", {
          body: notificationBody(message),
          tag: eventId ? `webchat:${pathKey}:${sessionId}:${eventId}` : `webchat:${pathKey}:${sessionId}`
        });
        notification.onclick = () => {
          window.focus();
          notification.close();
        };
      } catch (_) {}
    }

    function appendMessage(message, options = {}) {
      if (alreadySeen(message.id)) return;
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
      messages.appendChild(box);
      messages.scrollTop = messages.scrollHeight;
      if (message.id) lastEventId = Math.max(lastEventId, Number(message.id) || 0);
      if (options.notify) maybeNotifyAgentMessage(message);
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
        renderText(box, message.title || "客服笔记");
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
      statusText.textContent = data.enabled ? "在线" : "离线";
      if (!data.enabled && data.offline_msg) {
        appendMessage({ role: "system", kind: "text", text: data.offline_msg });
      } else if (data.waiting_hint) {
        appendMessage({ role: "system", kind: "text", text: data.waiting_hint });
      }
      renderQuickReplies(data.quick_replies || []);
      await loadHistory();
      connectStream();
    }

    function renderQuickReplies(items) {
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
          appendMessage({ role: "user", kind: "text", text: item.title });
          appendMessage({ role: "system", kind: "text", text: item.answer });
        });
        quickReplies.appendChild(btn);
      });
      quickReplies.hidden = false;
    }

    async function loadHistory() {
      if (!streamToken) return;
      const q = `session_id=${encodeURIComponent(sessionId)}&token=${encodeURIComponent(streamToken)}`;
      const resp = await fetch(`/api/history/${encodeURIComponent(pathKey)}?${q}`);
      if (resp.status === 401) {
        resetStoredSession();
        sessionId = cryptoRandom();
        streamToken = "";
        return;
      }
      if (!resp.ok) return;
      const data = await resp.json();
      if (!data.ok) return;
      messages.innerHTML = "";
      (data.events || []).forEach(appendMessage);
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
        const payload = JSON.parse(event.data);
        appendMessage(payload, { notify: true });
      });
    }

    async function sendMessage() {
      const text = input.value.trim();
      if (!text) return;
      requestNotificationPermission();
      input.value = "";
      appendMessage({ role: "user", kind: "text", text });
      persistSession();

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
      const data = await resp.json();
      if (!data.ok) {
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
      // 只有 session 变化或 stream 已关闭时才重连。
      if (sessionChanged || !stream || stream.readyState === 2) connectStream(true);
    }

    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) {
        connectStream();
      }
    });
    window.addEventListener("pagehide", () => {
      if (stream) { stream.close(); stream = null; }
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
