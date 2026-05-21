// WebChat 客服通知 Service Worker
// 用途:在移动端浏览器(Android Chrome 等)弹出「通栏通知」。
// 普通页面里的 new Notification(...) 在移动端只会被静默忽略,必须经过
// ServiceWorkerRegistration.showNotification 才能出现系统横幅。

self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil((async () => {
    const allClients = await self.clients.matchAll({
      type: "window",
      includeUncontrolled: true
    });
    for (const client of allClients) {
      try {
        await client.focus();
        return;
      } catch (_) {}
    }
    if (self.clients.openWindow) {
      try { await self.clients.openWindow("/"); } catch (_) {}
    }
  })());
});
